# Arteta Bot 表情反应系统重构计划

**适用分支**：`feat/chromadb-memory`
**执行对象**：本地 Agent
**计划类型**：工程修改任务书
**目标**：将现有“积极/中立 vs 消极”的二分类随机表情系统，重构为“是否应发送 + 对话反应意图 + 素材多标签检索”的关联性表情系统。

---

## 1. 执行前约束

本地 Agent 开始修改前必须：

1. 阅读仓库根目录 `AGENTS.md`、`CLAUDE.md`。
2. 确认当前分支和工作区状态：

```bash
git branch --show-current
git status --short
git log -5 --oneline
```

3. 保存本轮基线提交：

```bash
git rev-parse HEAD
```

4. 不修改上一轮已完成的以下功能，除非本计划明确要求接线：
   - ReAct 调试式等待进度；
   - 长篇回答策略；
   - Web 时效性路由；
   - Agent Trace 默认显示策略；
   - 回复图片渲染系统。
5. 保持 Python 3.8 兼容：不得使用 `list[str]`、`str | None`、`match` 等较新语法。
6. 每个阶段单独提交，不进行无关格式化或大范围重命名。

---

## 2. 当前实现诊断

最新代码中的表情系统主要分布在：

```text
plugins/arteta_agent/response/mood.py
plugins/arteta_agent/tools/qq_actions.py
plugins/arteta_agent/response/style.py
plugins/arteta_agent/prompts.py
plugins/arteta_agent/runtime/service.py
plugins/arteta_agent/policy/service.py
plugins/arteta_agent/progress/formatter.py
tests/test_arteta_agent_mood_response.py
tests/test_arteta_agent_response_style.py
```

现状：

1. `mood.py` 通过关键词将回复分成：
   - `positive_neutral`
   - `negative`
2. `qq_actions.py` 将开心、赞同、思考、犹豫、无聊、冷场等全部归入 `positive_neutral`。
3. 选中类别后使用 `random.choice()` 在整个类别内随机抽取。
4. 表情目录本身未包含在审查 ZIP 中，运行时通过 `ARTETA_EMOJI_DIR` 指向外部白名单目录。
5. Prompt 仍要求主模型在强情绪时调用 `send_mood_emoji`，同时 finalizer 又会自动补发，存在双路径。
6. 当前冷却仅记录最近三轮“是否发送”，没有记录具体表情、反应类型和重复度。
7. `ResponseStyleProfile.allow_mood_emoji` 已具备场景门控基础，但当前 finalizer 没有完整使用该场景语义。

根本问题不是“中立情绪识别差”，而是：

> 表情选择依赖粗粒度情绪极性，而不是当前对话中需要完成的反应动作。

---

## 3. 重构目标

### 3.1 功能目标

将流程改为：

```text
最终正文生成
    ↓
Emoji Gate：当前是否适合自动发表情
    ↓
Reaction Classifier：识别对话反应意图
    ↓
Emoji Catalog：读取素材多标签元数据
    ↓
Candidate Scorer：按反应、强度、立场、主题评分
    ↓
Recent History：排除近期重复和连续滥发
    ↓
发送最高匹配候选之一
```

### 3.2 体验目标

- 不再把“思考”和“开心”视为同一类。
- 不再把“无语”和“悲伤”视为同一类。
- 低置信度时正常选择不发。
- 同一场景优先选语义匹配素材，而不是全目录随机。
- 保留一定随机性，但只在高分候选之间轮换。
- 表情是正文的补充，不应代替事实核验、技术回答或权限提示。

### 3.3 非目标

本轮不做：

- 实时视觉模型分析每一张表情；
- CLIP 向量数据库；
- 自动从互联网下载表情；
- 允许模型指定任意文件路径；
- 将表情进度暴露在 ReAct 等待消息中；
- 修改 QQ 图片发送和缩放的现有安全边界。

---

## 4. 反应分类体系

第一版只实现以下 12 类，避免过度细分：

| reaction | 中文含义 | 典型场景 | 推荐自动发送 |
|---|---|---|---|
| `celebration` | 庆祝、兴奋 | 赢球、绝杀、官宣 | 是 |
| `approval` | 认可、满意 | 用户观点准确、球队执行出色 | 可选 |
| `amused` | 被逗笑、觉得有趣 | 梗图、节目效果 | 是 |
| `teasing` | 轻度调侃、阴阳 | 对手翻车、群友整活 | 谨慎 |
| `surprised` | 震惊、意外 | 爆冷、突然消息 | 是 |
| `speechless` | 无语、难绷 | 离谱判罚、重复犯错 | 是 |
| `thinking` | 思考、观察 | 开放问题、战术权衡 | 低频 |
| `skeptical` | 怀疑、保留 | 转会传闻、可疑消息 | 可选 |
| `encouraging` | 鼓励、打气 | 用户不会题、球队低谷 | 谨慎 |
| `comforting` | 安慰、共情 | 受伤、失利、低落 | 可选 |
| `frustrated` | 恼火、不满 | 被绝平、争议判罚 | 是 |
| `sad` | 失落、遗憾 | 淘汰、重伤、离队 | 是 |

特殊值：

```text
none
```

`none` 是合法且常见的结果，不得强制映射到某个类别。

---

## 5. 新数据模型

新建：

```text
plugins/arteta_agent/emoji/models.py
```

建议数据结构：

```python
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class EmojiGateDecision(object):
    should_send: bool
    confidence: float = 0.0
    reason_codes: List[str] = field(default_factory=list)
    explicit_request: bool = False


@dataclass(frozen=True)
class EmojiReactionDecision(object):
    reaction: str = "none"
    intensity: str = "medium"
    stance: str = "shared_with_user"
    topic: str = "general"
    confidence: float = 0.0
    reason_codes: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class EmojiAsset(object):
    name: str
    path: str
    relative_path: str
    reactions: List[str] = field(default_factory=list)
    intensities: List[str] = field(default_factory=list)
    stances: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    avoid_contexts: List[str] = field(default_factory=list)
    weight: float = 1.0
```

允许值：

```text
intensity: low / medium / high
stance: shared_with_user / toward_user / toward_event / toward_claim
```

所有字符串必须通过白名单归一化，未知值回退到安全默认值或 `none`。

---

## 6. 模块拆分

新建目录：

```text
plugins/arteta_agent/emoji/
├── __init__.py
├── models.py
├── gate.py
├── classifier.py
├── catalog.py
├── selector.py
└── history.py
```

职责：

### `gate.py`

只判断是否适合发表情，不选择具体反应。

### `classifier.py`

根据用户消息、最终正文、Response Style 和路由/工具状态输出 `EmojiReactionDecision`。

### `catalog.py`

安全读取白名单目录和 `manifest.json`，兼容旧目录结构。

### `selector.py`

候选过滤、评分、Top-K 带权选择。

### `history.py`

记录最近发送记录，处理连续发送、具体素材重复和反应类型重复。

现有 `response/mood.py` 在过渡期保留兼容入口，但内部改为调用新模块。不要让 Runtime 同时维护两套选择逻辑。

---

## 7. Emoji Gate 设计

### 7.1 强制不发送场景

以下场景默认禁止自动表情：

- `[NO_REPLY]`；
- `PermissionRequired`；
- 当前回复是错误、超时、权限、策略、Trace、日志、配置结果；
- 当前任务是事实核验、来源说明或严肃新闻确认；
- 当前任务是纯数学、代码、算法、物理答题；
- 用户明确说不要发表情；
- `emoji.enabled=false`；
- `send_mood_emoji` 被行为策略禁用；
- 本轮已经显式调用过表情工具；
- 没有可用表情素材。

技术题的例外：用户表现出明显沮丧，并且分类为 `encouraging` 且置信度高时可以发送，但首轮建议关闭该例外，待数据充分后再开启。

### 7.2 强制发送场景

用户明确要求：

```text
发表情
发个表情
来个表情
发个开心的
用表情回应
```

此时绕过自动冷却，但仍必须遵守：

- 白名单目录；
- 文件大小；
- 文件扩展名；
- 路径逃逸防护。

显式请求没有指定反应时，允许分类器根据语境判断；无法判断时使用 `approval`，不要再使用 `positive_neutral`。

### 7.3 自动发送阈值

建议：

```text
confidence >= 0.75：允许自动发送
0.60 <= confidence < 0.75：只有 meme / celebration / strong social reaction 场景允许
confidence < 0.60：不发送
```

### 7.4 Response Style 接线

`ResponseStyleProfile.allow_mood_emoji` 应成为 Gate 的输入之一，而不是唯一决定因素。

逻辑：

```text
profile.allow_mood_emoji == false
    → 默认不自动发送
    → 但显式请求仍可发送
```

`meme` 和明显庆祝场景可允许，`current_news`、`serious` 默认禁止。

---

## 8. Reaction Classifier 设计

### 8.1 输入必须分离

不要把用户消息和机器人回复直接拼接后做关键词查找。分别传入：

```python
classify_reaction(
    user_text=...,
    assistant_text=...,
    response_mode=...,
    route_hint=...,
    trace_tool_names=...,
)
```

需要分别推断：

- 用户当前表达；
- 机器人最终立场；
- 本轮交流功能；
- 反应对象是用户、事件还是传闻。

### 8.2 第一阶段使用高精度规则

先实现可测试的规则分类器，不立即引入新的 LLM 调用。

示例规则：

```text
赢了 / 绝杀 / 官宣 / 起飞 → celebration
笑死 / 梗图 / 节目效果 / 绷不住 → amused
离谱 / 难绷 / 又来 / 这也行 → speechless
真的吗 / 靠谱吗 / 我不信 / 传闻 → skeptical
爆冷 / 居然 / 突然 / 没想到 → surprised
被绝平 / 裁判 / 红温 / 气死 → frustrated
淘汰 / 重伤 / 离队 / 遗憾 → sad
别急 / 能学会 / 慢慢来 → encouraging
抱抱 / 理解 / 确实难受 → comforting
```

必须处理否定和引用，避免：

```text
“这不是庆祝” → celebration
“为什么有人说笑死” → amused
```

最低要求：

- 否定词窗口；
- 引号/引用文本降权；
- 用户文本和最终回复分别计分；
- 最终回复中的机器人立场权重高于用户引用词。

### 8.3 第二阶段预留结构化分类器

规则无法判断时，允许后续增加低成本结构化分类器，但本轮不强制上线。

接口预留：

```python
ReactionClassifier = Callable[..., EmojiReactionDecision]
```

未来模型输出仅允许 JSON：

```json
{
  "reaction": "skeptical",
  "intensity": "medium",
  "stance": "toward_claim",
  "topic": "football_news",
  "confidence": 0.84,
  "reason_codes": ["unconfirmed_transfer_claim"]
}
```

不得输出隐藏推理过程。

---

## 9. 表情素材元数据

在运行时表情目录下增加：

```text
manifest.json
```

示例：

```json
{
  "version": 1,
  "assets": {
    "arteta_stare_01": {
      "file": "skeptical/arteta_stare_01.gif",
      "reactions": ["skeptical", "speechless"],
      "intensities": ["medium"],
      "stances": ["toward_claim", "toward_event"],
      "topics": ["football", "news", "meme"],
      "avoid_contexts": ["serious_injury", "bereavement"],
      "weight": 1.0
    }
  }
}
```

### 9.1 安全要求

`catalog.py` 必须：

- 只允许 manifest 中的相对路径；
- 使用 `resolve()` + `relative_to()` 防路径逃逸；
- 校验扩展名；
- 校验文件存在且为普通文件；
- 限制 manifest 文件大小；
- JSON 解析失败时记录安全日志并回退旧目录扫描；
- 不向模型暴露绝对路径；
- 不允许 manifest 覆盖 `MAX_EMOJI_BYTES` 等安全限制。

### 9.2 旧目录兼容

如果不存在 manifest，按旧目录名映射：

| 旧关键词 | 新 reaction |
|---|---|
| 开心、高兴、庆祝 | `celebration` |
| 赞同、满意 | `approval` |
| 思考、想想、分析 | `thinking` |
| 无聊、冷场、平淡 | `speechless` 或 `thinking`，需人工复核 |
| 生气、愤怒、红温 | `frustrated` |
| 哭、难过、遗憾 | `sad` |

旧 `positive_neutral` 目录不能继续整体映射为一个类别。必须根据文件名、子目录或迁移清单拆分；无法判断的素材标记为：

```text
reactions: ["approval"]
weight: 0.3
```

并进入待人工审核列表。

### 9.3 增加迁移脚本

新增：

```text
tools/build_emoji_manifest.py
```

功能：

- 扫描 `ARTETA_EMOJI_DIR`；
- 根据旧目录、文件名生成初始 manifest；
- 输出未识别素材清单；
- 默认不覆盖已有人工标签；
- 支持 `--dry-run`；
- 支持 `--output`；
- 不修改图片文件。

---

## 10. 候选评分与选择

替换当前：

```python
random.choice(candidates)
```

建议评分：

```text
reaction 精确匹配        +6
reaction 次级匹配        +3
stance 匹配              +2
intensity 匹配           +2
topic 匹配               +1
显式指定素材名           +8
avoid_context 命中       -100
最近 5 次使用过同文件    -8
上一轮使用过同 reaction  -3
素材未人工审核           -2
```

选择方式：

1. 过滤分数小于最低阈值的素材；
2. 按分数降序；
3. 取 Top 3；
4. 在 Top 3 中按 `score * weight` 做确定性带权选择；
5. 随机种子使用 `group_id + request_id + reaction`，避免测试不稳定。

没有达到阈值的候选时：

```text
不发送
```

不得回退到整个表情目录随机抽取。

---

## 11. 发送历史与防重复

替换 `_MOOD_EMOJI_HISTORY` 的布尔列表，记录：

```python
{
    "asset_name": "arteta_stare_01",
    "reaction": "skeptical",
    "automatic": True,
    "timestamp": 1234567890.0,
}
```

建议规则：

- 自动表情连续发送 2 轮后，下一轮至少静默 1 轮；
- 同一素材最近 5 次自动发送中不得重复；
- 同一 reaction 连续两次时降低评分；
- 显式请求不受频率冷却，但仍尽量避免同素材重复；
- 历史按群隔离；
- 内存历史最多保留 20 条；
- 本轮不要求持久化到数据库。

历史模块必须支持单元测试重置：

```python
reset_emoji_history_for_tests()
```

---

## 12. 工具接口兼容与改名策略

### 12.1 保留现有工具名

第一轮保留：

```text
send_mood_emoji
```

避免破坏行为策略键：

```text
tool.send_mood_emoji.disabled
```

以及既有测试、Trace 和工具注册。

### 12.2 扩展工具参数

新 Schema：

```json
{
  "type": "object",
  "properties": {
    "reaction": {"type": "string"},
    "intensity": {"type": "string"},
    "stance": {"type": "string"},
    "topic": {"type": "string"},
    "emoji_name": {"type": "string"},
    "reason_code": {"type": "string"},
    "mood": {"type": "string"}
  },
  "required": []
}
```

兼容转换：

```text
mood=positive_neutral → approval（低权重兼容）
mood=negative → frustrated（若文本含失落词则 sad）
```

新代码不得主动生成 `mood` 参数。

### 12.3 主模型不再直接负责自动表情

修改 `plugins/arteta_agent/prompts.py`：

删除：

```text
明显强情绪时必须调用 send_mood_emoji
```

改为：

```text
表情由最终回复阶段的反应系统自动决定。除非用户明确要求指定表情，否则不要主动调用 send_mood_emoji。
```

更优做法：在 `detect_contextual_tool_exclusions()` 中默认将 `send_mood_emoji` 从主模型工具 Schema 排除，仅显式表情请求时暴露；finalizer 仍可通过 registry 内部执行。

这样消除：

```text
主模型主动调用
+
finalizer 自动补发
```

的双路径。

---

## 13. `response/mood.py` 迁移方式

保留公开函数：

```python
maybe_send_mood_emoji(...)
```

内部流程改为：

```python
gate = decide_emoji_gate(...)
if not gate.should_send:
    return FinalizedResponse(content, 0)

reaction = classify_emoji_reaction(...)
if reaction.reaction == "none":
    return FinalizedResponse(content, 0)

asset = select_emoji_asset(...)
if asset is None:
    return FinalizedResponse(content, 0)

execute internal send_mood_emoji call
record history
```

旧函数：

```text
detect_forced_mood_emoji_args
_recent_auto_emoji_saturated
_record_mood_emoji_result
```

完成迁移后删除或改为兼容包装，不保留两套并行逻辑。

---

## 14. 观测与日志

增加结构化日志，但不得记录完整私密群消息。

建议字段：

```text
event=emoji_gate_decision
group_id_hash=...
should_send=true
explicit_request=false
reason_codes=[...]

 event=emoji_reaction_decision
 reaction=speechless
 intensity=high
 stance=shared_with_user
 confidence=0.88

 event=emoji_asset_selected
 asset_name=arteta_stare_01
 candidate_count=4
 selected_score=10.5
```

失败日志仅记录异常类型，不记录绝对路径、完整消息和敏感参数。

后续可统计：

- 自动表情发送率；
- `none` 占比；
- 各 reaction 使用分布；
- 同素材重复率；
- manifest 缺失/无效率；
- 用户主动关闭表情的比例。

---

## 15. 文件级修改清单

### 新增

```text
plugins/arteta_agent/emoji/__init__.py
plugins/arteta_agent/emoji/models.py
plugins/arteta_agent/emoji/gate.py
plugins/arteta_agent/emoji/classifier.py
plugins/arteta_agent/emoji/catalog.py
plugins/arteta_agent/emoji/selector.py
plugins/arteta_agent/emoji/history.py
tools/build_emoji_manifest.py
tests/test_arteta_agent_emoji_gate.py
tests/test_arteta_agent_emoji_classifier.py
tests/test_arteta_agent_emoji_catalog.py
tests/test_arteta_agent_emoji_selector.py
tests/fixtures/emoji_manifest/manifest.json
```

### 修改

```text
plugins/arteta_agent/response/mood.py
plugins/arteta_agent/tools/qq_actions.py
plugins/arteta_agent/prompts.py
plugins/arteta_agent/routing/contextual_tools.py
plugins/arteta_agent/response/style.py
plugins/arteta_agent/progress/formatter.py
tests/test_arteta_agent_mood_response.py
tests/test_arteta_agent_response_style.py
Docs/dev/personality-response-acceptance.md
Docs/dev/personality-response-manual-evidence.md
```

### 不应修改

```text
plugins/arteta_agent/tools/web/
plugins/arteta_agent/progress/qq_reporter.py
plugins/arteta_agent/response/length_policy.py
```

除非仅为接线且有明确测试证明必要。

---

## 16. 测试矩阵

### 16.1 Gate 测试

| 输入 | 预期 |
|---|---|
| “塔子在吗” / “在。” | 不发 |
| “发个表情” | 发 |
| “不要发表情” | 不发 |
| 数学题正常解答 | 不发 |
| 权限确认 | 不发 |
| Trace/策略查看 | 不发 |
| 当前新闻核验 | 不发 |
| 梗图且回复明显被逗笑 | 可发 |
| 连续自动发送达到冷却 | 不发 |

### 16.2 Reaction 分类测试

| 场景 | 预期 reaction |
|---|---|
| “萨卡绝杀了！” | `celebration` |
| “领先两球又被扳平” | `speechless` 或 `frustrated`，规则必须稳定 |
| “这消息靠谱吗？” | `skeptical` |
| “前五句像遗书，最后突然晋级” | `amused` |
| “球员重伤赛季报销” | `sad`，禁止 `teasing` |
| “这不是庆祝，这是讽刺” | 不得判为 `celebration` |
| 引用别人说“笑死”并询问含义 | 不得仅凭引用判为 `amused` |

### 16.3 Catalog 安全测试

- manifest 正常加载；
- manifest 缺失回退；
- JSON 损坏回退；
- `../` 路径逃逸拒绝；
- 绝对路径拒绝；
- 非图片扩展名拒绝；
- 大文件仍由现有限制阻止；
- manifest 中不存在文件跳过；
- 重复 `file` 去重。

### 16.4 Selector 测试

- reaction 精确匹配优先；
- `avoid_contexts` 一票否决；
- 近期素材降权；
- 无匹配候选返回 `None`；
- 固定 seed 时结果稳定；
- Top-K 内才允许轮换；
- 不再回退到全目录随机。

### 16.5 兼容测试

- 旧 `mood=positive_neutral` 仍能执行；
- 旧 `mood=negative` 仍能执行；
- `tool.send_mood_emoji.disabled` 继续生效；
- 表情发送失败不影响主回复；
- `send_pending_mood_emojis()` 行为不退化；
- GIF 动图缩放仍保留动画；
- Trace 中仅显示参数名，不暴露绝对路径。

---

## 17. 人工验收样例

本地 Agent 必须输出一份：

```text
Docs/dev/reaction-emoji-manual-evidence.md
```

至少包含以下 12 组输入、正文、Gate、Reaction、候选 Top 3、最终素材：

1. 赢球庆祝；
2. 绝杀；
3. 被绝平；
4. 离谱判罚；
5. 转会传闻怀疑；
6. 突然官宣震惊；
7. 梗图接梗；
8. 严重伤病；
9. 用户不会数学题；
10. 普通“在吗”；
11. 用户明确要求表情；
12. 用户明确禁止表情。

每例必须说明为什么发送或不发送，不能只给最终文件名。

---

## 18. 提交顺序

### Commit 1

```text
refactor: add emoji reaction data models and gate
```

内容：models、gate、基础测试。

### Commit 2

```text
feat: classify conversational emoji reactions
```

内容：classifier、否定/引用处理、分类测试。

### Commit 3

```text
feat: load tagged emoji manifest safely
```

内容：catalog、manifest 迁移工具、安全测试。

### Commit 4

```text
feat: rank and deduplicate emoji candidates
```

内容：selector、history、稳定轮换测试。

### Commit 5

```text
refactor: route mood finalizer through reaction system
```

内容：`mood.py`、`qq_actions.py`、旧参数兼容、双路径移除。

### Commit 6

```text
test: add reaction emoji acceptance coverage
```

内容：完整测试、人工证据文档、开发文档更新。

每次提交前执行：

```bash
python -m compileall plugins/arteta_agent
pytest -q <本阶段相关测试>
git diff --check
git status --short
```

最终执行：

```bash
pytest -q
```

若全量测试存在仓库既有失败，必须记录：

- 失败测试名；
- 是否可在基线提交复现；
- 与本轮修改是否相关。

不得通过删除测试、放宽关键断言或吞掉异常来伪造通过。

---

## 19. 验收标准

满足以下全部条件才可标记完成：

- [ ] 新代码主动使用 `reaction`，不再主动生成 `positive_neutral/negative`。
- [ ] 普通中性回复不发表情。
- [ ] 强情绪场景能稳定区分至少 8 种 reaction。
- [ ] “思考、怀疑、无语、开心”不再共享同一候选池。
- [ ] 低置信度返回 `none`，不回退随机。
- [ ] 表情素材支持多标签 manifest。
- [ ] 路径白名单与文件大小限制无退化。
- [ ] 同一素材不会在短时间内反复出现。
- [ ] 严重伤病等场景不会选中调侃类素材。
- [ ] 主模型与 finalizer 不再双重触发表情。
- [ ] 行为策略禁用和显式请求继续有效。
- [ ] 表情失败不影响正文发送。
- [ ] Python 3.8 编译通过。
- [ ] 定向测试和全量测试结果已记录。
- [ ] 人工验收文档包含 12 个场景。

---

## 20. 最终交付物

本地 Agent 完成后提交：

```text
1. Git commit 列表
2. git diff <baseline>...HEAD --stat
3. 定向测试输出
4. 全量测试输出
5. Docs/dev/reaction-emoji-manual-evidence.md
6. 一份实际 ARTETA_EMOJI_DIR 的 manifest.json
7. 未识别或低置信度素材清单
8. 修改完成报告
```

完成报告必须明确标注：

```text
PASS
PASS WITH FOLLOW-UP
CHANGES REQUESTED
```

不得只写“已完成”。

---

## 21. 给本地 Agent 的最终执行指令

> 以本计划为唯一表情系统改造依据。优先保持现有 QQ 发送、安全白名单、行为策略和 finalizer 接口兼容。先建立 Gate、Reaction 和 Catalog，再替换随机二分类选择；不要先大改工具注册或 Runtime。任何无法可靠分类的场景都返回 `none`，不得为了提高表情发送率而扩大关键词或回退到随机素材。表情关联性优先于发送频率。
