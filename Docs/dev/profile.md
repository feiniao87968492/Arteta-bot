# 个人档案与人格画像系统

## 1. 背景

在早期版本中，LLM 对群成员的认知完全依赖当前对话上下文，无法区分不同成员的历史发言和信息，经常出现混淆（例如将 A 说过的事张冠李戴到 B 身上）。为了让"阿尔特塔"真正认识每一位球员，需要建立一套**永久性的个人档案系统**，记录每个用户的昵称变更历史、发言记录等基础信息。

在档案系统运行一段时间后，我们进一步引入了**人格画像系统**：当用户发言数量达到一定阈值时，自动调用 LLM 分析该用户的历史发言，生成结构化的性格画像，让主教练不仅知道"谁说过什么"，还了解"这个人是什么样的"。

---

## 2. 个人档案系统

### 2.1 数据库表

个人档案系统依赖三张核心数据库表，均在 `plugins/arteta_chat.py` 的 `init_db()` 中创建：

**`players` 表（原有，为基础表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | TEXT | QQ 号 |
| `group_id` | TEXT | 群号 |
| `nickname` | TEXT | 当前群昵称 |
| `level` | TEXT | 身份定位（默认"青训生"） |
| `favorability` | INTEGER | 信任度/好感度（默认 0） |
| `last_seen` | INTEGER | 最后活跃时间戳 |
| `profile_json` | TEXT | 人格画像 JSON（默认 `'{}'`，后迁移添加） |

主键为 `(user_id, group_id)`。

**`nicknames` 表（历史昵称记录）**

```sql
CREATE TABLE IF NOT EXISTS nicknames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    nickname TEXT NOT NULL,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    UNIQUE(user_id, group_id, nickname)
);
```

记录每个用户在每个群中使用过的所有昵称及其首次/最后出现时间。

**`messages` 表（发言历史）**

```sql
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    message TEXT NOT NULL,
    timestamp INTEGER NOT NULL
);
```

记录用户的每一条发言，用于统计分析以及作为 LLM 画像分析的素材。

### 2.2 核心函数

#### `update_nickname_history(user_id, group_id, nickname)`

在 `get_player_data()` 开始时调用。逻辑：

1. 查询 `nicknames` 表中是否已存在 `(user_id, group_id, nickname)` 记录。
2. 若存在，仅更新其 `last_seen` 为当前时间戳。
3. 若不存在，插入一条新记录，`first_seen` 和 `last_seen` 均为当前时间戳。

这样既能追踪昵称变更的时间线，也能避免重复记录同一昵称。

**调用入口**：`get_player_data()` 第 934 行：

```python
await update_nickname_history(user_id, group_id, nickname)
```

#### `save_message(user_id, group_id, message)`

在 `process_chat()` 中，对每条用户消息（非指令、非自定义 prompt）调用。将消息原文和当前时间戳写入 `messages` 表。

**调用入口**：`process_chat()` 第 1155 行：

```python
await save_message(user_id, group_id, raw_message)
```

#### `get_user_profile(user_id, group_id)`

构建用户完整档案字典，供 `/档案` 命令使用。返回字典结构：

```python
{
    "user_id": str,
    "current_nickname": str,       # 当前群昵称
    "level": str,                  # 身份定位
    "favorability": int,           # 信任度
    "last_seen": int,              # 最后活跃时间戳
    "nicknames": [                 # 历史昵称列表（最近10个，按 last_seen 降序）
        {"nickname": str, "first_seen": int, "last_seen": int},
        ...
    ],
    "recent_messages": [           # 最近发言（最近20条，按时间降序）
        {"message": str, "timestamp": int},
        ...
    ],
    "message_count": int,          # 发言总数
    "personality_profile": dict    # 人格画像 JSON 解析后的字典
}
```

### 2.3 命令

- `/档案` / `/profile` / `/个人档案` — 查看自己的档案
- `@某用户` 后跟 `/档案` — 可查看他人的档案（档案命令检测消息中的 `at` 消息段）

**命令定义**：

```python
profile_cmd = on_command("档案", aliases={"profile", "个人档案"}, priority=6, block=True)
```

### 2.4 显示内容

档案以图片形式渲染输出（通过 `text_to_tactical_board()` 转为战术板风格图片），包含：

1. **球员详细档案**
   - 姓名（当前群昵称）
   - 号码（QQ 号）
   - 定位（身份等级，如青训生/一线队/传奇队长等）
   - 信任度（好感度数值）
   - 上次训练（最后活跃时间）
   - 发言总数

2. **历史昵称记录**
   - 最多展示最近 5 个历史昵称
   - 每个昵称显示首次出现 ~ 最后出现的时间范围（格式：`月-日`）

3. **最近发言记录**
   - 最多展示最近 5 条发言
   - 每条显示时间戳（格式：`月-日 时:分`）和消息内容（超过 30 字截断）

4. **主教练对你的了解**（人格画像，详见下一节）
   - 真实姓名、外号/别名、性格特征、兴趣爱好、支持球队、讨厌球队
   - 说话风格、背景信息、你们的关系、值得记住的事

---

## 3. 人格画像系统

### 3.1 数据库扩展

人格画像数据存储在 `players` 表的 `profile_json` 列中（TEXT 类型，默认 `'{}'`）。该列通过数据库迁移方式添加：

```python
try:
    c.execute("ALTER TABLE players ADD COLUMN profile_json TEXT DEFAULT '{}'")
except sqlite3.OperationalError:
    pass  # 列已存在
```

此外，每次画像更新时，会记录变更历史到 `profile_updates` 表：

```sql
CREATE TABLE IF NOT EXISTS profile_updates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    old_profile TEXT,
    new_profile TEXT,
    trigger_message TEXT,
    timestamp INTEGER NOT NULL
);
```

### 3.2 JSON 结构

每次调用 LLM 分析后，会生成并存储如下结构的 JSON：

```json
{
    "real_name": "...",
    "nicknames": ["...", "..."],
    "personality": "性格特征",
    "interests": "兴趣爱好",
    "favorite_team": "支持的球队",
    "rival_teams": "讨厌的球队",
    "speaking_style": "说话风格",
    "background": "背景信息",
    "relationship_with_arteta": "与阿尔特塔的关系描述",
    "notable_events": "值得记住的关键事件",
    "last_profile_update": 1746000000,
    "message_count_at_update": 42
}
```

字段说明：

| 字段 | 说明 |
|------|------|
| `real_name` | 真实姓名（如果用户提到过） |
| `nicknames` | 所有已知的外号、别名、绰号（列表形式） |
| `personality` | 性格特征（开朗/内向/暴躁/幽默等） |
| `interests` | 兴趣爱好（不限于足球） |
| `favorite_team` | 支持的球队（从发言中推断） |
| `rival_teams` | 讨厌的球队 |
| `speaking_style` | 说话风格（正式/随意/粗鲁/礼貌/口头禅等） |
| `background` | 背景信息（学生/打工人/年龄/学校/职业等） |
| `relationship_with_arteta` | 与阿尔特塔的关系描述 |
| `notable_events` | 值得记住的关键事件 |
| `last_profile_update` | 最后一次更新的 Unix 时间戳 |
| `message_count_at_update` | 更新时的总发言数 |

### 3.3 更新触发策略

由 `should_update_profile()` 函数判定：

```python
async def should_update_profile(user_id: str, group_id: str, message_count: int) -> bool:
```

判定逻辑（按优先级）：

1. **冷却期检查**：距离上次更新不足 10 分钟（600 秒）时，不触发更新。这是为了避免频繁调用 LLM API 造成浪费和速率限制问题。
2. **新用户初始化**：如果当前没有任何画像数据（`personality` 字段为空）且消息数 >= 3 条，触发首次初始化。
3. **时间阈值**：距离上次更新超过 24 小时（86400 秒），触发更新。
4. **消息数量阈值**：距离上次更新后新增 >= 5 条消息，触发更新。

**触发入口**：在 `process_chat()` 的消息处理流程末尾（约第 1337 行）：

```python
if await should_update_profile(user_id, group_id, msg_count):
    asyncio.create_task(update_user_profile(user_id, group_id, nickname, lvl, fav))
```

使用 `asyncio.create_task()` 异步执行，不阻塞主聊天流程。

### 3.4 核心函数

#### `get_message_count(user_id, group_id) -> int`

查询 `messages` 表，统计指定用户在指定群的发言总数。用于配合 `message_count_at_update` 计算新增消息数。

#### `should_update_profile(user_id, group_id, message_count) -> bool`

见 3.3 节。返回 `True` 或 `False`。

#### `update_user_profile(user_id, group_id, nickname, level, favorability)`

核心画像更新逻辑：

1. 从数据库读取当前 `profile_json`。
2. 调用 `get_message_count()` 获取用户总消息数。
3. 查询最近 20 条发言记录，格式化为 `[月-日 时:分] 消息内容` 的文本。
4. 使用 `PROFILE_ANALYSIS_PROMPT` 构建 LLM 分析 prompt，包含：
   - 当前已有档案（保留已有信息）
   - 最近 20 条发言（用于提取新信息）
   - 当前昵称、身份等级、信任度
5. 调用 DeepSeek API（`deepseek-chat` 模型，temperature 0.3），要求只输出 JSON。
6. 解析 LLM 返回的 JSON，更新 `players` 表的 `profile_json` 列。
7. 将旧画像、新画像、触发消息和时间戳写入 `profile_updates` 表。

**关于 prompt 的关键设计**：

- 保留原有信息中仍然准确的部分，根据新发言修正或补充。
- 对于不确定的推测，标注"（推测）"。
- 重点提取方向：真实姓名/外号、年龄/学校/工作、口头禅、糗事/秘密、与其他成员的关系。
- 仅输出 JSON，不附带任何其他文字。

#### `get_profile_section(user_id, group_id) -> str`

从数据库中读取并格式化用户画像，返回一段文本描述，用于注入到 LLM 对话 prompt 中。这样主教练在每次对话时都能"记住"对这名球员的了解。

输出格式：

```
【球员个人档案——你对这名球员的了解】：
真实姓名：...
外号/别名：...
性格特征：...
兴趣爱好：...
支持球队：...
讨厌球队：...
说话风格：...
背景信息：...
你们的关系：...
值得记住的事：...
```

如果用户没有画像数据（`profile_json` 为空或 `personality` 为空），返回空字符串，不会影响正常对话。

### 3.5 分析 Prompt 定义

见 `PROFILE_ANALYSIS_PROMPT`（第 474-527 行），完整 prompt 要求 LLM 扮演记忆分析师，关注以下维度：

- `real_name`: 真实姓名（如果提到过）
- `nicknames`: 所有已知的外号、别名、绰号（列表形式）
- `personality`: 性格特征
- `interests`: 兴趣爱好
- `favorite_team`: 支持的球队（从发言中推断）
- `rival_teams`: 讨厌的球队
- `speaking_style`: 说话风格
- `background`: 背景信息（学生/打工人/年龄/学校/职业/所在地等）
- `relationship_with_arteta`: 与阿尔特塔的关系描述
- `notable_events`: 值得记住的关键事件（越多越好）

---

## 4. 数据流总结

```
用户发送消息
  │
  ├─→ save_message()                    —— 写入 messages 表
  │
  ├─→ get_player_data()
  │     └─→ update_nickname_history()    —— 写入/更新 nicknames 表
  │
  ├─→ 完整聊天流程（LLM 调用、好感度更新等）
  │
  └─→ should_update_profile()           —— 判断是否触发画像更新
        └─→ update_user_profile()        —— 异步调用 LLM 更新 profile_json
              └─→ 写入 profile_updates    —— 记录变更历史

用户输入 /档案
  └─→ get_user_profile()
        └─→ 返回完整档案字典 → 渲染图片 → 输出
```

## 5. 文件位置

- 所有代码：`plugins/arteta_chat.py`
- 数据库文件：`arsenal_data.db`（位于项目根目录）
- 渲染函数：`text_to_tactical_board()` 来自 `plugins/arteta_render.py`
