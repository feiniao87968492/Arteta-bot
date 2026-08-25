# 好感度系统 — 双架构设计

> 开发者文档：理解好感度的评估、计算与存储。

## 1. 背景

好感度系统经历了从纯关键词匹配到 LLM 主导的架构演进。

- **早期方案**：仅依赖关键词黑名单进行扣分，缺乏对正面互动的识别能力，也无法区分不同程度的负面行为。
- **当前方案**：以 LLM 标记评估为主系统，关键词扣分为辅助系统。LLM 根据对话上下文综合判断球员表现，输出结构化标记；关键词系统在 LLM 评估基础上额外扣分，作为安全兜底。

---

## 2. 双架构设计

### 2.1 主系统 — LLM 标记评估

LLM 被要求在每次回复正文结束后另起一行，输出一个好感度标记。标记定义在 `FAVOR_MARKERS` 字典中：

```python
FAVOR_MARKERS = {
    "【好感度+++】": (380, 770, "令人惊叹的表现，极大提升了信任度"),
    "【好感度++】":  (200, 370, "出色的交流，大幅提升了信任度"),
    "【好感度+】":   (10,  190, "积极的互动，提升了信任度"),
    "【好感度=】":   (0,    0,  ""),
    "【好感度-】":   (-190, -10, "不当言行，降低了信任度"),
    "【好感度--】":  (-370, -200, "严重的负面言行，大幅降低了信任度"),
    "【好感度---】": (-770, -380, "极端恶劣的言行，信任度严重受损"),
}
```

每个标记对应一个 `(min, max, reason)` 三元组：

- `min` / `max`：好感度变化的取值范围（正值为上升，负值为下降），实际变化值在该区间内随机选取。
- `reason`：红字显示的原因描述。`【好感度=】` 无原因。

**提取逻辑** (`extract_favor_marker()`):

1. 用正则遍历所有标记模式，记录每个匹配出现的位置。
2. 按位置排序，取**最后一个**出现的标记。
3. 若未找到任何标记，返回 `None`（好感度不变，inc=0）。

```python
def extract_favor_marker(text: str) -> Optional[str]:
    """从 LLM 回复中提取好感度标记（取最后一个出现的）"""
    found = []
    for marker in FAVOR_MARKERS:
        for m in re.finditer(re.escape(marker), text):
            found.append((m.start(), marker))
    if not found:
        return None
    found.sort(key=lambda x: x[0])
    return found[-1][1]
```

提取到标记后，计算基础 delta：

```python
min_val, max_val, marker_reason = FAVOR_MARKERS[marker]
if min_val != 0:
    inc = random.randint(min(min_val, max_val), max(min_val, max_val))
```

注意 `random.randint()` 要求第一个参数 ≤ 第二个参数，因此代码中使用了 `min()` / `max()` 对取值区间做归一化。`【好感度=】` 的 min=max=0，直接跳过随机，inc 保持为 0。

### 2.2 辅助系统 — 关键词扣分

`check_keyword_penalty()` 维护三层负面关键词列表，在 LLM 评估的基础上**叠加额外扣分**：

| 级别 | 变量名 | 扣分范围 | 示例关键词 |
|------|--------|---------|-----------|
| 重度 | `FAVOR_HEAVY_NEGATIVE` | -80 ~ -40 | 狗屎、傻逼、cnm、垃圾球队、阿尔特塔滚、塔嗨、nmsl |
| 中度 | `FAVOR_MODERATE_NEGATIVE` | -40 ~ -15 | 废物、垃圾、sb、滚、恶心、菜鸡、娜娜 |
| 轻度 | `FAVOR_LIGHT_NEGATIVE` | -20 ~ -5 | 菜、无语、失望、摆烂、拉胯、抽象、难绷 |

**匹配规则**：

- 发言全文转为小写后逐一匹配关键词子串。
- 按重度→中度→轻度顺序检测，**命中任一即返回**（不继续匹配更低级别）。
- 若同时触发多个同级别关键词，只取第一个命中的（顺序决定）。
- 返回 `(penalty, reason)` 元组，`reason` 格式为 `（触发敏感词：{kw}）`。
- 管理员 (`ADMIN_QQ`) 跳过关键词检测。

**叠加方式**：关键词扣分与 LLM 标记的 inc 直接相加：

```python
kw_penalty, kw_reason = check_keyword_penalty(prompt)
if kw_penalty < 0:
    inc += kw_penalty
```

这意味着标记为正（如 `【好感度+】` inc=50）但发言包含负面关键词时，最终 inc 可能被抵消为负值。

---

## 3. 数据流

```
用户发言
    │
    ▼
LLM 回复 → extract_favor_marker() 提取标记
    │
    ├── 标记存在 → 从 FAVOR_MARKERS 取 (min, max)
    │              → random.randint(min, max) 得基础 delta
    │
    ├── 标记为 【好感度=】 → inc = 0
    │
    └── 标记不存在 → inc = 0（记录日志）
            │
            ▼
    check_keyword_penalty(prompt)
        │
        ├── 命中重度词 → inc += random.randint(-80, -40)
        ├── 命中中度词 → inc += random.randint(-40, -15)
        ├── 命中轻度词 → inc += random.randint(-20, -5)
        └── 无命中    → 无额外扣分
            │
            ▼
    apply_favor_change(user_id, group_id, nickname, inc)
        │
        ├── 管理员 → favorability = 999999, level = '传奇队长'
        └── 普通球员 → 更新 players 表 favorability 和 level
            │
            ▼
    拼接红字 → 追加到回复末尾
```

### 完整调用链

好感度更新发生在 `process_chat()` 的 LLM 回复后处理阶段（`plugins/arteta_chat.py`）：

1. `extract_favor_marker(answer)` — 从 LLM 回复中提取最后一个标记，计算基础 inc。
2. `check_keyword_penalty(prompt)` — 对原始用户发言检测负面关键词，叠加额外扣分。
3. `apply_favor_change(...)` — 写入数据库，更新等级。
4. 将红字文本追加到 `answer` 末尾，随回复一起渲染发送。

---

## 4. 等级阈值

等级根据 favorability 数值在 `apply_favor_change()` 中自动计算。定义在 `FAVOR_LEVEL_THRESHOLDS` 中：

| 等级 | 好感度范围 | 说明 |
|------|-----------|------|
| 传奇队长 | ≥ 500 | 最高信任，球队灵魂人物 |
| 核心首发 | 200 ~ 499 | 稳定的核心成员 |
| 一线队 | 50 ~ 199 | 常规活跃成员 |
| 青训生 | 0 ~ 49 | 默认初始等级 |
| 预备队 | -50 ~ -1 | 表现欠佳，进入观察名单 |
| 看台内鬼 | < -50 | 最低等级，负面行为累积 |

**计算逻辑**（升序遍历，取第一个 `fav < threshold` 的等级，若全部不满足则为最后一项）：

```python
FAVOR_LEVEL_THRESHOLDS = [
    ("看台内鬼", -50),    # fav < -50
    ("预备队",    0),     # -50 <= fav < 0
    ("青训生",   50),     # 0 <= fav < 50
    ("一线队",  200),     # 50 <= fav < 200
    ("核心首发", 500),    # 200 <= fav < 500
    ("传奇队长", inf),    # fav >= 500
]
```

**新用户默认值**：`level = '青训生'`，`favorability = 0`。

---

## 5. 红字规则

好感度变动以红字形式追加到 LLM 回复末尾。**红字的生成由代码保证，不依赖 LLM 合规性**：

| 条件 | 红字格式 |
|------|---------|
| `inc > 0` | `[red]【信任度上升X点 - 原因】[/red]` |
| `inc < 0` | `[red]【信任度下降X点 - 原因】[/red]` |
| `inc == 0` | `[red]【信任度无变化】[/red]` |

其中原因来源优先级：
1. `FAVOR_MARKERS` 定义的 `reason`（如 "积极的互动，提升了信任度"）。
2. 若有额外关键词扣分，将 `kw_reason` 拼接在 `reason` 之后。
3. 若 inc 为 0（标记不存在或为 【好感度=】），直接显示无变化。

---

## 6. 数据库字段

好感度数据存储在 `arsenal_data.db` 的 `players` 表中，涉及两个字段：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `favorability` | INTEGER | 0 | 好感度数值，正值为信任，负值为不信任 |
| `level` | TEXT | '青训生' | 对应的等级名称，由 `apply_favor_change()` 自动计算 |

建表语句：

```sql
CREATE TABLE IF NOT EXISTS players (
    user_id TEXT,
    group_id TEXT,
    nickname TEXT,
    level TEXT DEFAULT '青训生',
    favorability INTEGER DEFAULT 0,
    last_seen INTEGER,
    profile_json TEXT,
    PRIMARY KEY (user_id, group_id)
);
```

---

## 7. 特殊规则

### 7.1 管理员不参与好感度变动

管理员 (`ADMIN_QQ = "2648955710"`) 的 favorability 固定为 `999999`，等级固定为 `'传奇队长'`，每次对话后重置：

```python
if is_admin:
    # 管理员固定满值
    UPDATE ... SET favorability = 999999, level = '传奇队长'
```

管理员也跳过关键词扣分检测。

### 7.2 新用户初始保护

新用户首次插入时，favorability 取 `max(0, inc)`。即若首次交互 inc 为负值（如初次发言就触发关键词扣分），初始好感度仍然为 0 而非负数，给予用户缓冲。

### 7.3 等级下限

系统未设置 favorability 的绝对下限。`apply_favor_change()` 直接累加 `favorability + inc`，因此 favorability 可以持续下降。等级系统为五档分级，即使 favorability 降至 -1000，等级也只会停留在"看台内鬼"，不会产生新的语义等级。

---

## 8. 相关命令

| 指令 | 触发词 | 功能 |
|------|--------|------|
| `好感度` | `/好感度` | 查询个人好感度与等级 |
| `好感度排行` | `/好感度排行` / `/排行` / `/ranking` / `/信任度排行` | 查看全群信任度 TOP10 和 BOTTOM10 排行（条形图） |

---

> 本文档基于 `plugins/arteta_chat.py` 中的 `FAVOR_MARKERS`、`extract_favor_marker()`、`check_keyword_penalty()`、`apply_favor_change()` 实现编写。如有疏漏，请以源码为准。
