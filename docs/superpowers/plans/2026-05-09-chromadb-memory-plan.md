# ChromaDB 群体记忆 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将对话记忆从进程内 `deque(maxlen=4)` 迁移到 ChromaDB 向量数据库，实现持久化、按群隔离、语义检索；同时修复 WebSocket 因 25s 阻塞导致的心跳断联。

**Architecture:** 新增 `arteta_memory.py` 封装 ChromaDB PersistentClient，提供 `add_memory()` / `query_memories()` 接口。`arteta_chat.py` 引入该模块替换 deque，LLM 调用改用 `asyncio.create_task` 后台执行，主协程立即回复"教练在写战术板..."。

**Tech Stack:** chromadb, sentence-transformers (all-MiniLM-L6-v2), asyncio

---

### Task 1: 安装 ChromaDB 依赖

**Files:**
- Environment: 服务器 Python 环境

- [ ] **Step 1: 在服务器安装 chromadb 和 sentence-transformers**

```bash
pip install chromadb sentence-transformers
```

- [ ] **Step 2: 验证安装**

```bash
python3 -c "import chromadb; import sentence_transformers; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git commit --allow-empty -m "chore: add chromadb and sentence-transformers deps"
```

---

### Task 2: 创建 arteta_memory.py — ChromaDB 封装模块

**Files:**
- Create: `plugins/arteta_memory.py`

- [ ] **Step 1: 编写 arteta_memory.py**

```python
"""ChromaDB 群体记忆 - 持久化对话历史 + 语义检索"""

import logging
import os
import time
from datetime import datetime

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

CHROMA_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chroma_db")
COLLECTION_NAME = "group_memories"
MAX_DOC_LENGTH = 1000  # 单条记忆的最大字符数
N_RESULTS = 5  # 每次检索返回条数


class MemoryStore:
    """ChromaDB 记忆存储封装，全局单例"""

    def __init__(self):
        self.client = None
        self.collection = None
        self._ready = False

    def initialize(self):
        """初始化 ChromaDB PersistentClient 和 collection"""
        try:
            self.client = chromadb.PersistentClient(
                path=CHROMA_DB_DIR,
                settings=Settings(anonymized_telemetry=False),
            )
            try:
                self.collection = self.client.get_collection(COLLECTION_NAME)
            except Exception:
                self.collection = self.client.create_collection(COLLECTION_NAME)
            self._ready = True
            logger.info(f"[MemoryStore] ChromaDB 初始化成功，数据目录: {CHROMA_DB_DIR}")
        except Exception as e:
            self._ready = False
            logger.error(f"[MemoryStore] ChromaDB 初始化失败: {e}")

    def add_memory(self, group_id: str, user_id: str, user_msg: str, assistant_reply: str):
        """将一轮对话存入 ChromaDB"""
        if not self._ready:
            return

        content = f"User: {user_msg}\nAssistant: {assistant_reply}"
        if len(content) > MAX_DOC_LENGTH:
            content = content[:MAX_DOC_LENGTH]

        ts = time.time()
        doc_id = f"{group_id}_{int(ts)}_{user_id[-8:]}"

        try:
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
        except Exception as e:
            logger.warning(f"[MemoryStore] add_memory 失败: {e}")

    def query_memories(self, group_id: str, query_text: str) -> list:
        """按语义检索本群相关历史对话，返回格式化字符串列表"""
        if not self._ready:
            return []

        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=N_RESULTS,
                where={"group_id": str(group_id)},
            )
        except Exception as e:
            logger.warning(f"[MemoryStore] query_memories 失败: {e}")
            return []

        if not results or not results["documents"] or not results["documents"][0]:
            return []

        formatted = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            ts = meta.get("timestamp", 0)
            date_str = datetime.fromtimestamp(ts).strftime("%m月%d日")
            formatted.append(f"--- {date_str} ---\n{doc}")

        return formatted


# 全局单例
memory_store = MemoryStore()
```

- [ ] **Step 2: 验证语法**

```bash
python3 -c "import ast; ast.parse(open('plugins/arteta_memory.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add plugins/arteta_memory.py
git commit -m "feat(memory): ChromaDB 记忆存储封装模块"
```

---

### Task 3: 在 arteta_chat.py 中集成 ChromaDB 记忆

**Files:**
- Modify: `plugins/arteta_chat.py`

- [ ] **Step 1: 在文件头部添加 import**

找到 `from plugins.arteta_render import text_to_tactical_board, html_to_image` 这行，在其后添加：

```python
from plugins.arteta_memory import memory_store
```

- [ ] **Step 2: 在 bot 启动时初始化 ChromaDB**

找到以下代码段（driver 相关配置部分之后，约 70-80 行附近）：

```python
# 高速缓存
tactical_cache = {"report": "", "last_update": 0}
user_memories = {}
```

在这之后添加：

```python
# ChromaDB 持久化记忆（在 bot 连接时初始化）
memory_store.initialize()
```

- [ ] **Step 3: 替换 deque 记忆读取逻辑**

找到以下代码段（约 1274-1278 行）：

```python
    if user_id not in user_memories:
        user_memories[user_id] = deque(maxlen=4)

    messages = [{"role": "system", "content": base_prompt}]
    messages.extend(list(user_memories[user_id]))
```

替换为：

```python
    messages = [{"role": "system", "content": base_prompt}]

    # 从 ChromaDB 检索本群相关历史记忆
    memory_contexts = memory_store.query_memories(group_id, user_message)
    if memory_contexts:
        memory_block = "\n\n".join(memory_contexts)
        memory_banner = f"\n\n【相关历史对话（本群）】：\n{memory_block}\n"
        # 注入到 base_prompt 末尾（再追加到 system content 中）
        messages[0]["content"] += memory_banner
```

- [ ] **Step 4: 替换 deque 记忆写入逻辑**

找到以下代码段（约 1293 行）：

```python
            user_memories[user_id].append({"role": "user", "content": user_message})
```

以及约 1340 行：

```python
            user_memories[user_id].append({"role": "assistant", "content": answer})
```

将这两处替换为 ChromaDB 存储调用（把 user 和 assistant 合并为一个 memory 轮次，第二次出现时已经拿到 answer）：

约 1293 行（原始的 `user_memories[user_id].append({"role": "user"...})`）：

删除这行（不再单独存 user 消息，等 assistant 回复后一起存）。

约 1340 行（`user_memories[user_id].append({"role": "assistant"...})`）：

替换为：

```python
            memory_store.add_memory(group_id, user_id, user_message, answer)
```

- [ ] **Step 5: 验证语法**

```bash
python3 -c "import ast; ast.parse(open('plugins/arteta_chat.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add plugins/arteta_chat.py
git commit -m "feat(memory): 集成 ChromaDB 替换 deque 对话记忆"
```

---

### Task 4: 修复 WebSocket 断联 — async background task

**Files:**
- Modify: `plugins/arteta_chat.py`

- [ ] **Step 1: 将主 LLM 调用改为后台任务**

找到以下代码段（约 1287-1288 行）：

```python
    try:
        answer = await asyncio.wait_for(run_tool_loop(messages), timeout=25.0)
```

替换为：

```python
    # 立即发送提示消息（不阻塞心跳）
    await bot.send(event, Message("📋 教练在战术板上写分析，马上就好..."))

    # 后台运行 LLM 调用，避免阻塞事件循环
    async def delayed_response():
        try:
            answer = await asyncio.wait_for(run_tool_loop(messages), timeout=30.0)
        except asyncio.TimeoutError:
            await bot.send(event, Message("⏰ 教练这次思考太久，重新说一遍？"))
            return
        except Exception as e:
            await bot.send(event, Message(f"连接中断：{str(e)}"))
            return
```

- [ ] **Step 2: 将后续处理逻辑移入 delayed_response**

将原 try 块内 `if answer:` 及之后的所有代码（好感度提取、关键词检测、好感度变更、图片渲染、发送）移到 `delayed_response` 函数内。原有缩进保持不变。

确保 `delayed_response` 的 `finally` 块外通过 `asyncio.create_task` 启动：

找到原 try 块的 `except Exception as e:`（约 1360 行）：

```python
    except Exception as e:
        await bot.send(event, Message(f"连接中断：{str(e)}"))
```

整个替换为：

```python
    try:
        answer = await asyncio.wait_for(run_tool_loop(messages), timeout=30.0)
    except asyncio.TimeoutError:
        await bot.send(event, Message("⏰ 教练这次思考太久，重新说一遍？"))
        return
    except Exception as e:
        await bot.send(event, Message(f"连接中断：{str(e)}"))
        return

    # --- 以下为原有的 answer 处理逻辑（好感度、渲染、发送）---
    if answer:
        with open("/tmp/debug.log", "a") as df:
            df.write(f"FC answer (first 500): {answer[:500]}\n")

        # --- LLM 好感度评估 ---
        inc, reason = 0, ""
        marker = extract_favor_marker(answer)
        is_admin = (user_id == ADMIN_QQ)
        if marker and marker in FAVOR_MARKERS:
            min_val, max_val, marker_reason = FAVOR_MARKERS[marker]
            if min_val != 0:
                inc = random.randint(min(min_val, max_val), max(min_val, max_val))
            reason = marker_reason
            answer = re.sub(r'\s*' + re.escape(marker) + r'\s*$', '', answer).rstrip()
        else:
            with open("/tmp/debug.log", "a") as df:
                df.write(f"[FAV] user={user_id} no marker found\n")

        # --- 关键词辅助检测 ---
        kw_penalty, kw_reason = check_keyword_penalty(prompt) if not is_admin else (0, "")
        if kw_penalty < 0:
            inc += kw_penalty
            reason = (reason + kw_reason) if reason else kw_reason.lstrip("（").rstrip("）")

        # --- 好感度变更 ---
        if not is_admin:
            lvl, fav = await apply_favor_change(user_id, group_id, nickname, inc)
        else:
            lvl, fav = await apply_favor_change(user_id, group_id, nickname, 0, is_admin=True)

        # --- 写入 ChromaDB 记忆 ---
        memory_store.add_memory(group_id, user_id, user_message, answer)

        # --- 检查是否需要更新画像 ---
        if await should_update_profile(user_id, group_id, msg_count):
            asyncio.create_task(update_user_profile(user_id, group_id, nickname, lvl, fav))

        # --- 好感度变动红字 ---
        if inc > 0:
            answer += f"\n\n[red]【信任度上升{abs(inc)}点 - {reason}】[/red]"
        elif inc < 0:
            answer += f"\n\n[red]【信任度下降{abs(inc)}点 - {reason}】[/red]"
        else:
            answer += f"\n\n[red]【信任度无变化】[/red]"

        # --- 渲染并发送 ---
        if needs_html_render(answer):
            html_answer = answer.replace("[red]", '<span class="arsenal-red">')
            html_answer = html_answer.replace("[/red]", '</span>')
            html_answer = html_answer.replace("[blue]", '<span class="arsenal-blue">')
            html_answer = html_answer.replace("[/blue]", '</span>')
            try:
                img_bytes = await html_to_image(html_answer)
            except Exception as e:
                img_bytes = text_to_tactical_board(answer)
        else:
            img_bytes = text_to_tactical_board(answer)
        await bot.send(event, MessageSegment.image(img_bytes))
    else:
        await bot.send(event, Message("让我想想再回答你。"))

    # 启动后台任务（注意：实际在 create_task 中调用）
```

- [ ] **Step 3: 启动后台任务**

在 `delayed_response` 定义之后、函数体之外，添加：

```python
    asyncio.create_task(delayed_response())
```

完整的代码结构变为：

```python
    await bot.send(event, Message("📋 教练在战术板上写分析，马上就好..."))

    async def delayed_response():
        try:
            answer = await asyncio.wait_for(run_tool_loop(messages), timeout=30.0)
        except asyncio.TimeoutError:
            await bot.send(event, Message("⏰ 教练这次思考太久，重新说一遍？"))
            return
        except Exception as e:
            await bot.send(event, Message(f"连接中断：{str(e)}"))
            return

        if answer:
            # ... 好感度、记忆存储、渲染、发送（完整代码见 Step 2）...
        else:
            await bot.send(event, Message("让我想想再回答你。"))

    asyncio.create_task(delayed_response())
```

- [ ] **Step 4: 验证语法**

```bash
python3 -c "import ast; ast.parse(open('plugins/arteta_chat.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: 删除旧的 timeout 常数（如存在）**

搜索文件中是否存在 `TIMEOUT = 25` 或类似常数，如有则改为 `30` 或删除。

- [ ] **Step 6: Commit**

```bash
git add plugins/arteta_chat.py
git commit -m "fix: WebSocket 断联 - LLM 调用改后台任务不阻塞心跳"
```

---

### Task 5: 清理旧 deque 代码

**Files:**
- Modify: `plugins/arteta_chat.py`

- [ ] **Step 1: 删除无用的 import 和全局变量**

删除以下 import（如果文件中没有其他使用）：

```python
from collections import deque
```

删除全局变量：

```python
user_memories = {}
```

- [ ] **Step 2: 验证语法**

```bash
python3 -c "import ast; ast.parse(open('plugins/arteta_chat.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add plugins/arteta_chat.py
git commit -m "refactor: 清理旧的 deque 记忆代码"
```

---

### Task 6: 服务器部署

**Files:**
- Deploy: `plugins/arteta_memory.py`
- Deploy: `plugins/arteta_chat.py`

- [ ] **Step 1: 服务器安装依赖**

```bash
ssh arteta "pip install chromadb sentence-transformers"
```

- [ ] **Step 2: 上传代码**

```bash
scp plugins/arteta_memory.py plugins/arteta_chat.py arteta:/opt/arteta_bot/plugins/
```

- [ ] **Step 3: 重启机器人**

```bash
ssh arteta "chown arteta:arteta /opt/arteta_bot/plugins/arteta_memory.py /opt/arteta_bot/plugins/arteta_chat.py && supervisorctl restart arteta_bot"
```

- [ ] **Step 4: 验证加载成功**

```bash
ssh arteta "tail -15 /var/log/arteta_bot/access.log | grep -E 'arteta_memory|MemoryStore|ERROR'"
```

Expected: 包含 `ChromaDB 初始化成功`，无 `ERROR`。

- [ ] **Step 5: 功能验证**

在群里发一条消息，确认：
1. 立即收到 "📋 教练在战术板上写分析，马上就好..."
2. 数秒后收到实际回复图片
3. WebSocket 不再断联（观察 5 分钟）

- [ ] **Step 6: 查看 ChromaDB 数据目录**

```bash
ssh arteta "ls -la /opt/arteta_bot/chroma_db/"
```

Expected: 目录存在且有 chroma.sqlite3 等文件。
