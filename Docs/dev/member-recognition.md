# 成员识别与人际关系系统

> 开发者文档：让阿尔特塔认识更衣室里的每一位球员，了解谁和谁经常互动。

---

## 1. 背景

Arteta Bot 的核心体验之一是"教练记得每一位球员"。这要求系统不仅存储球员的持久化档案，还要实时感知：

- **更衣室里有谁**：当前群内活跃成员名单，以及他们的身份定位和好感度。
- **谁在和谁互动**：球员之间的回复/@ 关系网络，让阿尔特塔可以在聊天中自然提及球员之间的社交联系。

这些数据通过两个渠道注入：每次对话时自动注入活跃成员快照（Prompt 层面），以及通过 Function Calling 工具按需查询详细数据。

---

## 2. 数据库

### member_relations 表

位于 `arsenal_data.db`，记录球员之间的回复/@ 互动次数。

```sql
CREATE TABLE IF NOT EXISTS member_relations (
    user_id TEXT NOT NULL,
    target_user_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    interaction_count INTEGER DEFAULT 1,
    last_interaction_time INTEGER NOT NULL,
    PRIMARY KEY (user_id, target_user_id, group_id)
);
```

- `user_id`：发起互动的球员 QQ 号。
- `target_user_id`：被回复或 @ 的球员 QQ 号。
- `interaction_count`：累计互动次数，每次触发 +1。
- `last_interaction_time`：最近一次互动的时间戳（Unix 秒数）。
- 联合主键 `(user_id, target_user_id, group_id)` 确保不会重复记录同一条关系。

建表位置：`plugins/arteta_chat.py` 第 454-460 行，`init_db_safely()` 函数内。

---

## 3. 互动追踪

### 触发时机

在 `process_chat()` 中，每次收到群消息时检测两种互动模式（位于第 1191-1212 行）：

1. **回复消息**：通过 `event.reply` 获取被回复者 `user_id`。
2. **@ 提及**：遍历消息段中 `type == "at"` 的段，提取 `qq` 字段。

### 记录函数

```python
async def track_member_interaction(user_id, target_id, group_id):
    """记录用户 A 与用户 B 之间的互动（回复/@），建立关系数据"""
    now = int(time.time())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""INSERT INTO member_relations (...)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(...)
            DO UPDATE SET interaction_count = interaction_count + 1, ...""",
            (user_id, target_id, group_id, now, now))
        await db.commit()
```

### 过滤规则

以下情况不会被记录（第 1204、1211 行）：

- **自互动**：`target_id == user_id`（自己回复自己或 @ 自己）。
- **Bot 互动**：`target_id == bot.self_id`（回复或 @ 机器人本身不记录）。

---

## 4. Function Calling 工具

定义在 `plugins/arteta_tools.py`，注册在 `TOOLS` 列表中供 DeepSeek 调用。

### get_group_members

获取群内近 24 小时活跃的球员名单。

- **名称**：`get_group_members`
- **参数**：`group_id`（群号）
- **SQL**：从 `players` 表 LEFT JOIN `messages` 表，筛选近 86400 秒内有发言记录的球员，按发言数降序排列，取前 20 名。
- **返回内容**：每位球员的昵称、身份等级（如传奇队长★、核心首发◆）、好感度、发言次数。
- **定义位置**：第 102-117 行（工具 schema），第 359-386 行（实现函数 `_get_group_members`）。

### get_member_relations

查询某位球员互动最多的群成员。

- **名称**：`get_member_relations`
- **参数**：`group_id`（群号）、`user_id`（球员 QQ 号）
- **查询逻辑**：双向查询。正向查该球员对谁的互动最多（按 `interaction_count` 降序，取前 8）；反向查谁经常找该球员互动（取前 5）。
- **返回内容**：正向和反向的互动列表，含对方昵称和互动次数。
- **定义位置**：第 119-138 行（工具 schema），第 389-429 行（实现函数 `_get_member_relations`）。

### 在 Prompt 中的引导

`ARTETA_PROMPT` 第 96-98 行明确告知 LLM 这两个工具的存在和用途：

> 你认识群里的每一位活跃球员。可以使用 get_group_members 工具了解更衣室里的球员名单、他们的身份定位和信任度；使用 get_member_relations 工具了解球员之间的互动关系。当谈到群内其他球员或问起更衣室氛围时，主动利用这些信息让回复更有针对性。

---

## 5. Prompt 注入 — 更衣室概况

在每次 `process_chat()` 执行时，自动注入一个活跃成员快照到 `base_prompt` 中。

### 函数：get_active_members_snapshot()

```python
def get_active_members_snapshot(group_id, limit=8) -> str:
```

位于 `plugins/arteta_chat.py` 第 551-579 行。

- **查询范围**：近 24 小时有发言记录的球员。
- **排序**：按发言次数降序。
- **限制**：默认取前 8 名（`limit=8`）。
- **输出格式**：一行字符串，每位球员以顿号分隔，格式为：

  ```
  球员名●(好感85)、球员名★(好感120)、球员名○(好感40)
  ```

  其中图标根据身份等级显示：
  - 传奇队长：★
  - 核心首发：◆
  - 一线队：●
  - 青训生：○
  - 预备队：△
  - 看台内鬼：▼

### 在 base_prompt 中的位置

`base_prompt` 第 1259 行：

```
【更衣室概况】：{group_snapshot}
（你可以使用 get_group_members 查看完整活跃球员名单，
使用 get_member_relations 了解球员之间的关系。
```

这样阿尔特塔在每次回复前都能"看到"更衣室里谁在活跃，而不需要每次手动调用工具。

---

## 6. Bug Fix 说明

### UnboundLocalError: chain_text

**问题**：当用户发送的消息不是回复消息时，`chain_text` 变量仅在 `if reply_id:` 分支内被赋值（第 1183 行）。如果该分支未进入（`reply_id` 为 `None`），后续代码在第 1198 行引用 `chain_text` 时会抛出 `UnboundLocalError`。

**修复**：在第 1164 行显式初始化 `chain_text = ""`，确保无论是否检测到回复，该变量始终有定义。

**相关代码行**：

- 第 1164 行：`chain_text = ""`
- 第 1182-1183 行：仅在 `reply_id` 不为空时覆盖赋值
- 第 1198 行：`if not reply_to_id and chain_text:` — 现在即使没有回复也能安全执行
