# ChromaDB 群体记忆 — Design Doc

## 问题

当前对话记忆存在三个问题：

1. **无持久化**：`user_memories = {user_id: deque(maxlen=4)}` 全在进程内存里，重启即丢失
2. **只能按人隔离**：同一人在不同群的对话混在一起，A 群聊战术的记忆会污染 B 群吹水
3. **只能按最近轮次回忆**：deque 只保留最近 4 轮，更早的有价值对话无法被模型感知

另外 WebSocket 频繁断联的原因是 `asyncio.wait_for(run_tool_loop(), timeout=25)` 阻塞事件循环，心跳无法响应。

## 方案

引入 ChromaDB 向量数据库，将每轮对话转为向量存储，每次收到消息时**按语义检索**本群历史中的相关对话，替代当前的 `deque(maxlen=4)`。

## 架构

```
┌──────────────────┐     ┌──────────────────────┐
│  用户发消息       │────>│  1. 查询 ChromaDB     │
└──────────────────┘     │  检索本群相关历史      │
                         │  (metadata filter)    │
                         └──────────┬───────────┘
                                    │ top-5 结果
                         ┌──────────v───────────┐
                         │  2. 拼接 prompt       │
                         │  base_prompt +        │
                         │  相关记忆 + 用户消息   │
                         └──────────┬───────────┘
                                    │
                         ┌──────────v───────────┐
                         │  3. create_task 后台   │
                         │  运行 LLM (不阻塞)     │
                         └──────────┬───────────┘
                                    │
                      ┌─────────────v──────────────┐
                      │  4. 回复 "教练在写战术板…"  │
                      │  立即发送，不等待 LLM       │
                      └────────────────────────────┘
                                    │ (后台 LLM 完成后)
                         ┌──────────v───────────┐
                         │  5. 存入 ChromaDB     │
                         │  6. 发送结果图片       │
                         └──────────────────────┘
```

## 组件设计

### 1. ChromaDB Collection

- **Collection 名称**：`group_memories`
- **单 collection，用 metadata 隔离群**（而非每群一个 collection）
- **每条记录**存储一个对话轮次（用户消息 + 助理回复 组成一个 document）

Document 结构：

```python
{
    "id": f"{group_id}_{timestamp}_{user_id[:8]}",
    "content": "User: 今天萨卡状态怎么样\nAssistant: 萨卡今天表现非常出色...",
    "metadata": {
        "group_id": "123456",
        "user_id": "789012",
        "timestamp": 1680000000.0,
        "user_msg_preview": "今天萨卡状态怎么样",  # 方便调试
    }
}
```

### 2. Embedding 模型

使用 `sentence-transformers/all-MiniLM-L6-v2`：
- 轻量级（~80MB），本地运行无需外部 API
- 384 维向量，检索速度够快
- ChromaDB 原生支持传入 embedding function

### 3. 检索策略

- **查询时间**：每次用户发消息时检索
- **过滤条件**：`{"group_id": str(group_id)}`
- **排序**：按余弦相似度降序
- **Top-K**：取最相关的 5 条
- **注入 prompt 格式**：

```
【相关历史对话（本群）】：
--- 3月15日 ---
用户：萨卡最近怎么了
阿尔特塔：他需要更多休息，连续首发太多了

--- 3月20日 ---
用户：今天首发怎么排
阿尔特塔：我想试试热苏斯突前...
```

### 4. 热缓存（可选优化）

保留一个 `group_recent_messages: dict[str, deque] = {}`，key 为 group_id，存最近 10 轮原始消息（不做向量检索），用于：
- 快速提供最近几轮上下文（避免每次都查向量库）
- 补充语义检索可能遗漏的相邻对话

### 5. WebSocket 断联修复

**问题根因**：`asyncio.wait_for(run_tool_loop(messages), timeout=25.0)` 在 25 秒内阻塞事件循环，OneBot 心跳无法发出。

**修复方案**：

```python
# 旧代码
answer = await asyncio.wait_for(run_tool_loop(messages), timeout=25.0)

# 新代码
await bot.send(event, Message("📋 教练在战术板上写分析，马上就好..."))

async def delayed_response():
    answer = await run_tool_loop(messages)
    # ... 处理好感度、渲染图片 ...
    await bot.send(event, MessageSegment.image(img_bytes))

asyncio.create_task(delayed_response())
```

关键点：
- `run_tool_loop` 本身是 async 函数，await 它会阻塞
- `asyncio.create_task` 把 LLM 调用放到后台，协程立即返回
- 立即发送一条"正在思考"消息，LLM 完成后发第二条（实际回复）
- 心跳不受影响

### 6. 存储路径

ChromaDB 持久化目录：`chroma_db/`（项目根目录）
由 `PersistentClient(path="./chroma_db")` 管理，重启自动恢复。

### 7. 启动流程

```python
# bot 启动时
chroma_client = chromadb.PersistentClient(path="./chroma_db")
try:
    collection = chroma_client.get_collection("group_memories")
except:
    collection = chroma_client.create_collection("group_memories")
```

### 8. 依赖安装

```bash
pip install chromadb sentence-transformers
```

`chromadb` 会自动拉 `onnxruntime`，`sentence-transformers` 会自动拉 `transformers`、`torch`。

## 数据流详细流程

### 写入流程（LLM 回复完成后）

```python
# 当前对话
user_msg = "萨卡今天会上吗？"
assistant_reply = "萨卡今天首发，他训练状态很好..."

collection.add(
    documents=[f"User: {user_msg}\nAssistant: {assistant_reply}"],
    metadatas=[{
        "group_id": group_id,
        "user_id": user_id,
        "timestamp": time.time(),
        "user_msg_preview": user_msg[:50],
    }],
    ids=[f"{group_id}_{int(time.time())}_{user_id[-8:]}"]
)
```

### 读取流程（用户发消息时）

```python
results = collection.query(
    query_texts=[user_message],
    n_results=5,
    where={"group_id": group_id},
)

if results["documents"]:
    memory_context = "【相关历史对话（本群）】：\n"
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        timestamp = datetime.fromtimestamp(meta["timestamp"]).strftime("%m月%d日")
        memory_context += f"\n--- {timestamp} ---\n{doc}\n"
```

## 与现有系统的关系

- **SQLite (`arsenal_data.db`)**：球员档案、好感度、消息计数不变，仍走 SQLite
- **ChromaDB**：只存对话记忆，不做球员数据
- **现有 deque**：可删除（完全被 ChromaDB + 热缓存替代），或保留作为轻量热缓存
- **`base_prompt`** 结构不变，只是注入内容多了一段「相关历史对话」

## 边界情况处理

| 场景 | 处理方式 |
|------|---------|
| 群内首次对话 | ChromaDB `n_results=5` 返回空列表，跳过记忆注入 |
| ChromaDB 启动失败 | 捕获异常，降级为无记忆模式（不影响核心对话） |
| 同一秒多条消息 | ID 加随机后缀防冲突 |
| 消息过长 | 存入时截断 document 到 1000 字（metadata 保持轻量） |
| 记忆积累太多 | 定期（如每月）清理 30 天前的记录，或按 group_id 维度限制总量 |
| sentence-transformers 加载失败 | 降级为 ChromaDB 默认的 all-MiniLM-L6-v2 在线下载，或用 ChromaDB 内置的 embedding 函数兜底 |

## 性能考量

- `all-MiniLM-L6-v2` 单条编码 < 100ms（CPU），384 维向量检索 < 10ms
- 每次对话增加 1 次向量写入（~100ms）+ 1 次检索（~10ms）
- 对比当前 25s 的 LLM 调用，ChromaDB 开销可忽略
- 主要性能改善来自 WebSocket 解耦（阻塞 25s → 立即返回）
