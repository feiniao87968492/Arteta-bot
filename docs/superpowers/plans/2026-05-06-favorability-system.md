# 好感度系统改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改造好感度系统，支持大幅涨跌（±10-200）、更容易触发下降、机器人根据好感度等级表现不同情绪。

**Architecture:** 单文件修改（`plugins/arteta_chat.py`），保持现有流程不变。在 `update_and_get_player()` 中引入三级关键词检测+随机取值，在 `process_chat()` 中增强 LLM prompt 的语气指令，调整好感度等级阈值。

**Tech Stack:** Python, NoneBot, SQLite, DeepSeek API

---

### Task 1: 新增 import 和关键词常量

**Files:**
- Modify: `plugins/arteta_chat.py:13`（在 `from collections import deque` 之后新增 `import random`）

- [ ] **Step 1: 添加 import random**

在 `plugins/arteta_chat.py` 第 13 行 `from collections import deque` 之后插入 `import random`。

- [ ] **Step 2: 在 `update_and_get_player` 上方添加关键词常量**

在 `update_and_get_player` 函数定义之前（第 754 行之前），添加三级关键词列表和等级阈值常量：

```python
# --- 好感度关键词分级 ---
FAVOR_HEAVY_NEGATIVE = ["狗屎", "傻逼", "草泥马", "cnm", "尼玛死了", "垃圾球队", "解散吧", "废物教练", "垃圾教练",
                         "阿尔特塔滚", "arteta滚", "阿森纳滚"]
FAVOR_MODERATE_NEGATIVE = ["下课", "废物", "垃圾", "滚", "解雇", "退役", "s b", "sb", "脑残", "有毒", "倒闭", "菜鸡", "煞笔"]
FAVOR_LIGHT_NEGATIVE = ["菜", "不行", "无语", "哎", "算了", "没救", "失望", "摆烂", "真菜", "太菜"]
FAVOR_POSITIVE = ["coyg", "加油阿森纳", "好教练", "信任", "必胜", "相信塔子", "我们阿森纳是不可战胜的",
                   "相信阿尔特塔", "好塔子", "牛逼", "好球", "漂亮", "冠军"]

FAVOR_LEVEL_THRESHOLDS = [
    ("看台内鬼", -50),
    ("预备队", 0),
    ("青训生", 50),
    ("一线队", 200),
    ("核心首发", 500),
    ("传奇队长", float("inf")),
]
```

---

### Task 2: 重写 `update_and_get_player()` 函数

**Files:**
- Modify: `plugins/arteta_chat.py:755-774`

- [ ] **Step 1: 替换整个函数**

将原来第 755-774 行的 `update_and_get_player` 函数替换为：

```python
async def update_and_get_player(user_id: str, group_id: str, nickname: str, prompt: str):
    is_admin = (user_id == ADMIN_QQ)
    prompt_lower = prompt.lower()
    inc_value = 0
    reason = ""

    if not is_admin:
        # 1. 三级关键词检测
        if any(w in prompt_lower for w in FAVOR_HEAVY_NEGATIVE):
            inc_value = random.randint(-200, -100)
            reason = "发言中包含对球队/教练的恶意攻击"
        elif any(w in prompt_lower for w in FAVOR_MODERATE_NEGATIVE):
            inc_value = random.randint(-100, -40)
            reason = "发言中包含明显的负面言论"
        elif any(w in prompt_lower for w in FAVOR_LIGHT_NEGATIVE):
            inc_value = random.randint(-40, -10)
            reason = "发言中表达了轻微的不满"
        elif any(w in prompt_lower for w in FAVOR_POSITIVE):
            inc_value = random.randint(50, 200)
            reason = "展现了对球队的热情支持"
        else:
            inc_value = random.randint(10, 50)
            reason = "正常积极交流"

    # 更新昵称历史
    await update_nickname_history(user_id, group_id, nickname)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''INSERT INTO players (user_id, group_id, nickname, favorability, last_seen) VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(user_id, group_id) DO UPDATE SET favorability = favorability + ?, nickname = excluded.nickname, last_seen = excluded.last_seen''',
                         (user_id, group_id, nickname, 999999 if is_admin else 0, int(time.time()), 999999 if is_admin else inc_value))
        # 根据新阈值更新等级
        new_fav_raw = await db.execute_fetchone(
            "SELECT favorability FROM players WHERE user_id = ? AND group_id = ?", (user_id, group_id))
        current_fav = new_fav_raw[0] if new_fav_raw else 0
        new_level = "看台内鬼"
        for lvl, threshold in FAVOR_LEVEL_THRESHOLDS:
            if current_fav < threshold:
                new_level = lvl
                break
        await db.execute('''UPDATE players SET level = ? WHERE user_id = ? AND group_id = ?''',
                         (new_level, user_id, group_id))
        await db.commit()
        async with db.execute("SELECT level, favorability FROM players WHERE user_id = ? AND group_id = ?", (user_id, group_id)) as cursor:
            row = await cursor.fetchone()
            return (row[0], row[1], inc_value, reason) if row else ("未知", 0, inc_value, reason)
```

**注意：** 这里使用了 `db.execute_fetchone` — 但 aiosqlite 没有这个方法。需要改用 `await db.execute("SELECT favorability FROM ...")` 然后 `await cursor.fetchone()`。修复如下，在 `new_fav_raw = await db.execute_fetchone(...)` 之后改成：

```python
        async with db.execute("SELECT favorability FROM players WHERE user_id = ? AND group_id = ?", (user_id, group_id)) as cursor:
            row = await cursor.fetchone()
        current_fav = row[0] if row else 0
```

- [ ] **Step 2: 确认最终函数代码**

最终函数内容确认：

```python
async def update_and_get_player(user_id: str, group_id: str, nickname: str, prompt: str):
    is_admin = (user_id == ADMIN_QQ)
    prompt_lower = prompt.lower()
    inc_value = 0
    reason = ""

    if not is_admin:
        if any(w in prompt_lower for w in FAVOR_HEAVY_NEGATIVE):
            inc_value = random.randint(-200, -100)
            reason = "发言中包含对球队/教练的恶意攻击"
        elif any(w in prompt_lower for w in FAVOR_MODERATE_NEGATIVE):
            inc_value = random.randint(-100, -40)
            reason = "发言中包含明显的负面言论"
        elif any(w in prompt_lower for w in FAVOR_LIGHT_NEGATIVE):
            inc_value = random.randint(-40, -10)
            reason = "发言中表达了轻微的不满"
        elif any(w in prompt_lower for w in FAVOR_POSITIVE):
            inc_value = random.randint(50, 200)
            reason = "展现了对球队的热情支持"
        else:
            inc_value = random.randint(10, 50)
            reason = "正常积极交流"

    await update_nickname_history(user_id, group_id, nickname)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''INSERT INTO players (user_id, group_id, nickname, favorability, last_seen) VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(user_id, group_id) DO UPDATE SET favorability = favorability + ?, nickname = excluded.nickname, last_seen = excluded.last_seen''',
                         (user_id, group_id, nickname, 999999 if is_admin else 0, int(time.time()), 999999 if is_admin else inc_value))
        async with db.execute("SELECT favorability FROM players WHERE user_id = ? AND group_id = ?", (user_id, group_id)) as cursor:
            row = await cursor.fetchone()
        current_fav = row[0] if row else 0
        new_level = "看台内鬼"
        for lvl, threshold in FAVOR_LEVEL_THRESHOLDS:
            if current_fav < threshold:
                new_level = lvl
                break
        await db.execute('''UPDATE players SET level = ? WHERE user_id = ? AND group_id = ?''',
                         (new_level, user_id, group_id))
        await db.commit()
        async with db.execute("SELECT level, favorability FROM players WHERE user_id = ? AND group_id = ?", (user_id, group_id)) as cursor:
            row = await cursor.fetchone()
            return (row[0], row[1], inc_value, reason) if row else ("未知", 0, inc_value, reason)
```

---

### Task 3: 更新 `process_chat()` 中的解包和 prompt

**Files:**
- Modify: `plugins/arteta_chat.py:1010-1041`

- [ ] **Step 1: 更新解包和 fav_status 逻辑**

第 1010 行修改为接收 4 个返回值：

```python
    lvl, fav, inc, reason = await update_and_get_player(user_id, group_id, nickname, prompt)
```

- [ ] **Step 2: 替换信任度通知和个性化回复要求部分**

将第 1037-1041 行替换为：

```python
        f"【信任度态势】当前 {nickname} 信任度为 {fav}，等级为 {lvl}。"
        f"本次对话导致信任度{fav_status}了 {abs(inc)} 点（原因：{reason}）。\n"
        f"【回复纪律】根据球员等级严格执行以下态度：\n"
        f"- 传奇队长（信任度≥500）：热情拥抱，用'兄弟''老伙计'称呼，长篇激励\n"
        f"- 核心首发（信任度200-499）：积极肯定，鼓励保持状态，展现信任\n"
        f"- 一线队（信任度50-199）：正常沟通，积极回应\n"
        f"- 青训生（信任度0-49）：简短回应，略带审视，保持观察\n"
        f"- 预备队（信任度-50~-1）：言辞严肃，明确表达不满和失望\n"
        f"- 看台内鬼（信任度<-50）：直接表达愤怒，用词严厉，只给最短回应，"
        f"让他知道自己随时可能被清洗出队\n"
        f"【个性化回复要求】：根据你对该球员的了解，调整你的回复风格和态度。"
        f"如果他是热刺球迷，可以适当调侃；如果他是忠实枪迷，给予更多鼓励；"
        f"如果他说话风格粗鲁，你可以严厉一些；如果他礼貌认真，你也可以更温和。"
        f"表现出你记得和这名球员之间的过往互动。"
```

---

### Task 4: 更新 `handle_fav()` 好感度查询命令

**Files:**
- Modify: `plugins/arteta_chat.py:1194-1207`

- [ ] **Step 1: 替换 handle_fav 内容**

根据新等级体系更新输出文案：

```python
@fav_cmd.handle()
async def handle_fav(bot: Bot, event: MessageEvent):
    user_id, group_id = event.get_user_id(), str(event.group_id) if isinstance(event, GroupMessageEvent) else "private"
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT level, favorability FROM players WHERE user_id = ? AND group_id = ?", (user_id, group_id)) as cursor:
            row = await cursor.fetchone()
    if row:
        level = row[0]
        fav = row[1]
        # 根据等级定制态度描述
        attitude = {
            "传奇队长": "你是这支球队的灵魂人物，我完全信任你！继续带领大家前进！",
            "核心首发": "你正在证明自己的价值，保持住这种能量！",
            "一线队": "我看到你的努力了，继续用表现说话。",
            "青训生": "你还需要更多训练和比赛来证明自己。",
            "预备队": "你的态度让我很失望，需要重新证明你对这支球队的忠诚。",
            "看台内鬼": "你最好反思一下自己的言行，球队不需要破坏更衣室气氛的人。",
        }.get(level, "")
        reply = (
            f"[blue]个人表现评估[/blue]\n\n"
            f"队内定位：【{level}】\n"
            f"信任度：{fav}\n\n"
            f"{attitude}"
        )
        img_bytes = text_to_tactical_board(reply)
        await fav_cmd.finish(MessageSegment.image(img_bytes))
```

---

### Task 5: 更新 prompt 中的 profile 信任度引用

**Files:**
- Modify: `plugins/arteta_chat.py:1250-1290`（约在 `get_user_profile` 附近）

- [ ] **Step 1: 检查是否有其它地方引用了旧的等级阈值**

搜索文件中的 `>= 50`、`>= 20`、`>= 5`、`>= 0` 等旧阈值，更新为新的等级区间。如果 `get_user_profile()` 或 `handle_profile()` 中有硬编码的等级描述，同步更新。

---

### Task 6: 部署到服务器

**Files:**
- Modify: `plugins/arteta_chat.py`（SCP 上传）

- [ ] **Step 1: SCP 上传并重启**

```bash
scp D:\Users\zty\arteta_bot\plugins\arteta_chat.py arteta:/opt/arteta_bot/plugins/arteta_chat.py
ssh arteta "supervisorctl restart arteta_bot && sleep 2 && supervisorctl status arteta_bot"
```

- [ ] **Step 2: 验证日志**

```bash
ssh arteta "tail -5 /var/log/arteta_bot/access.log"
```

确认 `arteta_chat` 插件加载成功，无报错。
