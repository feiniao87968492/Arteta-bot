# ChromaDB 群体记忆 — 持久化对话语义检索

> 开发者文档：理解基于 ChromaDB 的群体对话记忆系统，包括存储、检索、爬坑记录。

## 1. 背景

早期对话记忆采用内存中的 `deque(maxlen=4)` 按用户隔离，存在三个问题：

- **无持久化**：重启进程即丢失全部对话历史，模型无法感知重启前的上下文。
- **只能按人隔离**：同一用户在不同群的对话混在一起，A 群聊战术的记忆会污染 B 群的日常聊天。
- **只能按最近轮次回忆**：deque 只保留最近 4 轮，更早的有价值对话无法被模型感知。

引入 ChromaDB 向量数据库后，每轮对话被转为向量存储，每次收到消息时**按语义检索**本群历史中的相关对话，替代原有的 deque 方案。

---

## 2. MemoryStore 类

代码位于 `plugins/arteta_memory.py`，封装了对 ChromaDB 的所有操作，全局单例模式。

### 2.1 `initialize()` — 初始化

```python
def initialize(self):
    self.client = chromadb.PersistentClient(
        path=CHROMA_DB_DIR,
        settings=Settings(anonymized_telemetry=False),
    )
    try:
        self.collection = self.client.get_collection(COLLECTION_NAME)
    except Exception:
        self.collection = self.client.create_collection(COLLECTION_NAME)
    self._ready = True
```

- 使用 `PersistentClient` 连接本地文件存储，非 HTTP 模式。
- 数据目录：项目根下的 `chroma_db/`（由 `CHROMA_DB_DIR` 计算得出）。
- 尝试获取已有 collection，不存在则创建。
- `_ready` 标志位控制后续操作是否执行；初始化失败时降级为无记忆模式，不阻塞核心对话。

### 2.2 `add_memory(group_id, user_id, user_msg, assistant_reply)` — 写入

```python
content = f"User: {user_msg}\nAssistant: {assistant_reply}"
# 截断超长文本
if len(content) > MAX_DOC_LENGTH:
    content = content[:MAX_DOC_LENGTH]

ts = time.time()
doc_id = f"{group_id}_{int(ts)}_{user_id[-8:]}"

self.collection.add(
    documents=[content],
    metadatas=[{
        "group_id": str(group_id),
        "user_id": str(user_id),
        "timestamp": ts,
        "user_msg_preview": user_msg[:50],
    }],
    ids=[doc_id],
)
```

- `MAX_DOC_LENGTH = 1000`：单条记忆最大字符数，超长截断。
- metadata 中的 `group_id` 用于后续查询过滤（群隔离）。
- `user_msg_preview` 是前 50 个字符的快照，方便调试。
- `doc_id` 格式：`{group_id}_{unix_timestamp}_{user_id 后 8 位}`，确保唯一性。

### 2.3 `query_memories(group_id, query_text)` — 检索

```python
results = self.collection.query(
    query_texts=[query_text],
    n_results=N_RESULTS,
    where={"group_id": str(group_id)},
)
```

查询参数：

| 参数 | 值 | 说明 |
|------|-----|------|
| `query_texts` | `[用户当前消息]` | 以当前用户消息作为查询文本 |
| `n_results` | 5 | 返回最相关的 5 条记忆 |
| `where` | `{"group_id": str(group_id)}` | 只检索本群对话，实现群隔离 |

返回结果以格式化字符串呈现：

```python
for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
    ts = meta.get("timestamp", 0)
    date_str = datetime.fromtimestamp(ts).strftime("%m月%d日")
    formatted.append(f"--- {date_str} ---\n{doc}")
```

---

## 3. Collection 配置

| 属性 | 值 |
|------|-----|
| Collection 名称 | `group_memories` |
| 数量 | 单个 collection，所有群共享 |
| 群隔离方式 | metadata 中的 `group_id` 字段 + `where` 过滤 |
| Embedding 模型 | `all-MiniLM-L6-v2`（ChromaDB 默认） |
| 向量维度 | 384 |
| 相似度度量 | 余弦相似度（ChromaDB 默认） |

选择单 collection + metadata 过滤，而非每群一个 collection，出于以下考虑：

- 管理简单：创建、备份、清理只需操作一个 collection。
- 资源节省：避免大量 collection 的元数据开销。
- 性能充足：384 维向量在万级规模下，带 metadata 过滤的检索仍 < 10ms。

---

## 4. 检索策略

### 4.1 查询时机

每次用户发消息时（`arteta_chat.py` 约第 1276 行）：

```python
memory_contexts = memory_store.query_memories(group_id, user_message)
if memory_contexts:
    memory_block = "\n\n".join(memory_contexts)
    memory_banner = f"\n\n【相关历史对话（本群）】：\n{memory_block}\n"
    messages[0]["content"] += memory_banner
```

### 4.2 Prompt 注入格式

检索到的记忆以如下格式注入到 system prompt 中：

```
【相关历史对话（本群）】：
--- 3月15日 ---
User: 萨卡最近怎么了
Assistant: 他需要更多休息，连续首发太多了

--- 3月20日 ---
User: 今天首发怎么排
Assistant: 我想试试热苏斯突前...
```

### 4.3 检索结果为空时的处理

ChromaDB `n_results=5` 返回空列表时，跳过记忆注入，不影响正常对话流程。

---

## 5. 写入时机

关键设计决策：在**LLM 回复完成后**写入，且 **BEFORE** 好感度红字拼接。

代码位置（`arteta_chat.py` 约第 1341 行）：

```python
# 1. 解析好感度标记
marker = extract_favor_marker(answer)
# ...
# 2. 应用好感度变更
lvl, fav = await apply_favor_change(...)
# 3. 更新用户画像
asyncio.create_task(update_user_profile(...))

# 4. 写入 ChromaDB ← 这里
memory_store.add_memory(group_id, user_id, user_message, answer)

# 5. 拼接红字 ← 之后
answer += f"\n\n[red]【信任度上升...】[/red]"
```

这么做的原因：

- 若不写入红字，存储的 assistant_reply 中不含 `[red]` 标签，保持内容的"纯净性"。
- 若先拼红字再写入，则后续检索到的对话中会包含 `[red]` 标签，污染检索语义，且模型回复时可能误输出 `[red]` 标签。

---

## 6. 爬坑记录

### 6.1 sqlite3 版本过低

**问题**：系统自带 sqlite3 3.31.1，低于 ChromaDB 要求的 3.35.0，启动时报错。

**修复**：使用 `pysqlite3-binary` 做 monkey-patch，在导入 ChromaDB 之前替换 `sys.modules["sqlite3"]`。

```python
try:
    import pysqlite3
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass
```

这段代码必须位于文件最顶部，在 `import chromadb` 之前执行。

### 6.2 posthog 版本冲突

**问题**：`posthog>=4` 使用了 `dict[str, X]` 语法（需要 Python 3.9+），但项目环境中 Python 版本较低。

**修复**：将 posthog 降级到 `<3` 版本（`posthog==2.x`），避免类型注解语法兼容性问题。

### 6.3 ChromaDB 版本选择

**问题**：ChromaDB 0.5.x 要求 Python 3.9+，在某些低版本环境中无法安装。

**修复**：锁定 `chromadb==0.4.x` 版本，兼容 Python 3.8 环境。

### 6.4 重复导入 asyncio

**问题**：早期代码中 `asyncio` 被重复导入（`import asyncio` 出现多次），虽不报错但不规范。

**修复**：合并为文件顶部单个 `import asyncio`，去除重复导入语句。

### 6.5 后台任务异常吞咽

**问题**：`asyncio.create_task(delayed_response())` 启动的后台任务若抛出未捕获的异常，默认被事件循环静默吞咽，无日志、无 Traceback。

**修复**：在 `delayed_response()` 内包裹全局 `try/except`，确保所有异常路径至少打印日志：

```python
async def delayed_response():
    try:
        answer = await asyncio.wait_for(run_tool_loop(messages), timeout=90.0)
    except asyncio.TimeoutError:
        # 打印日志 + 发送超时提示
        return
    except Exception as e:
        # 打印异常日志 + 发送错误提示
        return
```

---

## 7. 边界情况

| 场景 | 处理方式 |
|------|---------|
| 群内首次对话 | 检索结果为空，跳过记忆注入 |
| ChromaDB 初始化失败 | `_ready = False`，所有读写操作静默跳过 |
| 消息过长 | 截断 document 至 `MAX_DOC_LENGTH`（1000 字符） |
| 存储路径不存在 | `PersistentClient` 自动创建目录 |
| 同一秒多条消息 | ID 含毫秒精度的 timestamp + user_id 后缀，不会冲突 |

---

## 8. 文件位置

| 文件 | 作用 |
|------|------|
| `plugins/arteta_memory.py` | MemoryStore 类定义（单例） |
| `chroma_db/` | ChromaDB 持久化数据目录（gitignore） |
| `plugins/arteta_chat.py` | 使用方：检索（第 1276 行）和写入（第 1341 行） |
