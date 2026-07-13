# Arteta Bot 人设、表达与回复呈现优化执行计划

**目标分支：** `feat/chromadb-memory`
**执行对象：** 本地编码 Agent
**运行基线：** Python 3.8 兼容
**任务边界：** 本轮只处理人格表达、回复节奏、表情、信任度、Trace/Marker 与渲染；不修改 Web 安全、事实核验算法、ChromaDB 结构和 Agent 核心权限模型。

---

## 1. 背景与问题定义

当前回复已经具备明确观点和足球语境，但存在以下系统性问题：

1. Prompt 将“拍桌子”写成高频示例，并在每轮额外注入同类硬约束，导致固定开场。
2. “有活力”被实现为夸张动作、长段落和战术比喻，实际阅读节奏仍然僵硬。
3. 梗图、日常闲聊、新闻判断、战术分析使用同一种表达结构，缺乏场景差异。
4. `send_mood_emoji` 对所有非负面回复强制生成 `positive_neutral` 表情，表情失去稀缺性。
5. 好感度标记被强制塞进主回复 Prompt，随后随机产生 10～770 级别的变化，并在每条回复中红字展示，导致讨好倾向和数值通胀。
6. Agent Trace、`[grok]`、`markers:[grok]` 等内部状态进入正式回复卡片，破坏角色沉浸。
7. 图片模板顶部横幅和多层边框占用过多空间，正文层级单一；短回复也被迫渲染成长图。
8. 人设默认 Prompt 在 `plugins/arteta_chat.py`、Dashboard Prompt Service 等位置重复，容易出现生产配置漂移。
9. 缺少开场去重与最近表达约束，模型会从“拍桌子”迁移到新的固定口头禅。

本轮目标不是简单删除“拍桌子”，而是建立一套**按场景调整人格强度、长度、节奏和呈现方式**的回复系统。

---

## 2. 目标体验

### 2.1 人格目标

机器人应表现为：

- 有明确判断，但不机械“唱反调”或强行下结论；
- 有教练视角，但不每次都提更衣室、战术板、高位逼抢；
- 有活力，主要通过节奏、短句、反问、停顿和适度调侃体现；
- 面对新闻和传闻时谨慎区分事实、消息和个人判断；
- 面对梗图先接梗，不把笑点解释成战术论文；
- 面对严肃问题降低角色表演强度；
- 不描述“拍桌子、敲战术板、摊手、推门”等自身动作作为固定开场。

### 2.2 呈现目标

- 普通短聊天优先发送原生文本；
- 长分析、公式、代码、表格或明确视觉内容才使用图片；
- 默认不显示 Agent Trace；
- 默认不显示内部 Marker；
- 信任度普通变化不占据正文；
- 图片卡片提供清晰的结论、正文、来源等层级，而不是只堆装饰边框。

---

## 3. 设计原则

1. **人格核心稳定，表达模式动态。** 不为每个场景重写完整人设，只生成简短的场景风格约束。
2. **规则优先，避免新增一次 LLM 分类调用。** 先使用当前消息、附件、RouteDecision、Tool Trace 判断回复模式。
3. **主回复与系统评分解耦。** 好感度、Trace、表情都是后处理，不应污染主回复 Prompt。
4. **内部状态结构化保留，用户界面默认隐藏。** Marker 和 Trace 可用于审计，不直接展示。
5. **短消息不扩写。** 不再要求所有问题“详细回答”或默认 2～4 段。
6. **先行为修复，再视觉重构。** 避免 Prompt、信任度、Trace 和模板同时大改后无法定位回归。
7. **Python 3.8 兼容。** 使用 `List[str]`、`Optional[...]` 等写法，不使用 `list[str]`、`X | None`。

---

## 4. 目标结构

新增轻量风格模块：

```text
plugins/arteta_agent/response/
├── style.py            # 场景识别、人格强度、长度与渲染建议
├── mood.py             # 表情触发策略
├── favorability.py     # 好感度决策与展示策略
├── composer.py         # Marker/来源/最终文本组合
└── ...
```

核心模型：

```python
from dataclasses import dataclass, field
from typing import List, Literal


@dataclass(frozen=True)
class ResponseStyleProfile(object):
    mode: Literal[
        "casual",
        "meme",
        "football_opinion",
        "current_news",
        "tactical_deep_dive",
        "serious",
    ]
    persona_intensity: Literal["light", "medium", "strong"]
    target_length: Literal["short", "medium", "long"]
    allow_football_metaphor: bool = True
    allow_mood_emoji: bool = False
    prefer_image_render: bool = False
    reason_codes: List[str] = field(default_factory=list)
```

若项目要求严格 Python 3.8，`Literal` 可继续使用 `typing.Literal`；不得使用 3.10 联合类型语法。

---

## 5. 分阶段实施计划

## Phase 0：建立基线和回归样本

### 修改内容

1. 从真实群聊中整理至少 40 条匿名测试样例，覆盖：
   - 日常问候；
   - 梗图；
   - 普通足球观点；
   - 最新新闻与转会；
   - 战术深聊；
   - 严肃问题；
   - 用户明确要求表情；
   - 用户主动查看 Trace。
2. 每条样例标注：
   - 期望 `mode`；
   - 期望人格强度；
   - 目标长度；
   - 是否允许表情；
   - 是否应使用图片；
   - 是否展示 Trace；
   - 是否展示信任度。
3. 将两张当前问题截图对应的输入加入固定回归样例。

### 新增文件

```text
tests/fixtures/personality_eval_cases.json
tools/evaluate_personality_style.py
```

### 验收

- 测试样例能够由脚本加载；
- 评估脚本先输出当前基线，不要求本阶段全部通过；
- 记录当前“拍桌子”、表情必发、信任度必显、Trace 显示比例。

---

## Phase 1：统一人格 Prompt 单一来源

### 涉及文件

```text
plugins/arteta_chat.py
plugins/arteta_agent/prompts.py
dashboard/api/services/prompt_service.py
dashboard/api/services/bot_chat_service.py
config/prompts.json
tests/test_arteta_prompt_style.py
tests/dashboard/test_prompt_service.py
```

### 修改要求

1. 将默认人格正文集中到 `plugins/arteta_agent/prompts.py`：

```python
ARTETA_PERSONA_CORE = "..."
ARTETA_RESPONSE_RULES = "..."
```

2. `plugins/arteta_chat.py` 与 Dashboard 不再复制完整默认 Prompt，只导入同一默认值。
3. 保留持久化 Prompt 覆盖能力，但明确优先级：

```text
持久化覆盖 > 统一内置默认
```

4. 删除以下内容：
   - “可以先拍桌子”；
   - “第一句就要有劲”的硬性重复注入；
   - “无论对方问什么都要详细回答”；
   - “默认 2～4 个自然段”；
   - 主 Prompt 中的好感度死命令。
5. 新增明确约束：

```text
- 开场直接表达态度，但不要描述自己的肢体动作。
- 不固定使用“拍桌子、敲战术板、摊手、推门”等动作。
- 不要为了体现阿尔特塔身份而强行加入更衣室或战术比喻。
- 简单问题可以只回答 1～3 句。
- 梗图先接梗，最多补一个观察；除非用户要求，不展开成长篇分析。
- 新闻回答先区分已确认事实、传闻和个人判断。
```

6. 删除或改造 `append_current_turn_style_guard()`，禁止每轮追加同一个“有劲”模板。

### 验收

- 全仓库非文档区域搜索不到 `可以先拍桌子`；
- 默认 Prompt 只有一个权威来源；
- Dashboard 与 QQ 主流程读取同一默认 Prompt；
- Prompt 测试由“必须包含第一句有劲”改为“禁止固定动作并允许短答”。

---

## Phase 2：实现回复场景与人格强度

### 新增文件

```text
plugins/arteta_agent/response/style.py
tests/test_arteta_agent_response_style.py
```

### 场景判定

优先使用已有信息：

- 当前用户消息；
- 是否包含图片；
- 是否为引用链；
- RouteDecision/Intent；
- `current_information_required`；
- 已执行工具类型；
- 用户是否明确要求“详细分析”。

第一轮采用确定性规则，不新增分类 LLM。

### 推荐规则

| 场景 | 判断示例 | 人格强度 | 长度 |
|---|---|---:|---:|
| `casual` | 简单闲聊、短问答 | light | short |
| `meme` | 图片+“怎么看/笑死/这图” | light | short |
| `football_opinion` | 球员价值、阵容观点 | medium | medium |
| `current_news` | Web Required、转会、伤病、官宣 | medium | medium |
| `tactical_deep_dive` | 用户明确要求详细、战术机制 | strong | long |
| `serious` | 技术、隐私、道歉、敏感话题 | light | medium |

### 风格块生成

将 `ResponseStyleProfile` 转为不超过 8 行的本轮约束，例如：

```text
【本轮表达模式：梗图轻互动】
- 先接住笑点，直接说最有趣的反差。
- 控制在 1～3 个短段或 120 字以内。
- 不描述自己的动作，不强行上升到战术哲学。
- 可以轻微调侃，但不要解释每个笑点。
```

该约束应由统一 Prompt Builder 注入，不能在 `arteta_chat.py` 中散落字符串。

### 验收

- 两张截图对应样例分别判定为 `football_opinion` 与 `meme`；
- `meme` 默认不超过 120～180 字；
- 纯战术问题允许较长；
- 日常问题不再被强制扩成 4 段。

---

## Phase 3：开场去重与模板化表达抑制

### 修改内容

1. 从当前会话中提取最近 5～10 条助手回复的首句。
2. 实现：

```python
extract_opening_signature(text: str) -> str
build_recent_opening_guard(messages: List[dict]) -> str
```

3. 注入简短约束：

```text
最近已使用过的开场：……
本次不要重复或只做同义改写。
```

4. 增加固定动作检查：

```text
拍桌子
敲战术板
摊手
推开更衣室门
站起来说
```

第一轮只在测试与 Prompt 层阻止；不要直接对正常正文做粗暴字符串删除。

5. 可选第二道防线：当输出首句命中动作叙述或与最近开场高度相似时，仅做一次轻量重写，不重新运行工具。

### 验收

- 连续 10 条测试回复中，不得出现同一开场模板超过 2 次；
- 不出现固定动作开场；
- 重写过程不得丢失工具来源、结论和安全提示。

---

## Phase 4：修复表情必发问题

### 涉及文件

```text
plugins/arteta_agent/response/mood.py
plugins/arteta_agent/prompts.py
plugins/arteta_agent/tools/qq_actions.py
tests/test_arteta_agent_mood_response.py
tests/test_arteta_agent_registry.py
```

### 修改要求

1. 删除当前“非负面即 `positive_neutral`”的默认返回。
2. `detect_forced_mood_emoji_args()` 默认返回 `{}`。
3. 仅在以下情况强制表情：
   - 用户明确要求发表情或图片；
   - 明确强烈庆祝、挑衅、愤怒、失望等情绪；
   - 回复模式允许，且不是新闻、技术、Trace、权限、错误或严肃场景。
4. 普通积极/中立回复不强制调用表情工具，由模型自主选择或不发送。
5. 增加冷却：同一群或同一用户最近 3 个机器人回复已发表情时，不再自动发送；显式请求除外。
6. 表情失败不得影响正文。

### 验收

- 普通中立回复不调用 `send_mood_emoji`；
- 梗图可调用，但不是每次必发；
- Trace/新闻/错误回复不发；
- 用户明确要求时仍能发送；
- 更新旧测试 `test_agent_loop_forces_positive_neutral...`，不再维护错误行为。

---

## Phase 5：将信任度评估从主回复中解耦

### 涉及文件

```text
plugins/arteta_chat.py
plugins/arteta_agent/response/favorability.py
dashboard/api/services/bot_chat_service.py
dashboard/api/services/prompt_service.py
Docs/dev/favorability.md
tests/test_arteta_favorability.py
tests/test_arteta_chat_commands.py
```

### 修改要求

1. 主回复 Prompt 不再输出 `【好感度+++】` 等 Marker。
2. 回复生成后单独调用确定性评分器；第一轮不新增额外 LLM：
   - 普通提问、图片分享、正常讨论：`0`；
   - 明确高质量贡献、持续帮助群体：`+1～+3`；
   - 特殊事件：`+4～+8`；
   - 明确辱骂、恶意攻击：对称扣分；
   - 不再随机产生 10～770 点变化。
3. 保留现有数据库总值，不在本轮强制重算历史数据。
4. 普通 `0` 或小幅变化不显示。
5. 仅在以下情况显示：
   - 等级发生变化；
   - 单次变化达到配置阈值；
   - 用户主动查询；
   - 管理员开启调试显示。
6. 信任度提示不再自动加 `[red]`，避免触发图片渲染。
7. Dashboard 与 QQ 端使用同一评分区间和显示策略。
8. Memory 写入继续使用未附带信任度提示的纯正文。

### 验收

- 分享普通梗图不会再增加数百点；
- 普通回复不出现“信任度无变化”；
- 主回复不因信任度提示被迫渲染成图片；
- 等级变化时有简短提示；
- 数据库兼容原值。

---

## Phase 6：隐藏 Trace 与内部 Marker

### 涉及文件

```text
plugins/arteta_chat.py
plugins/arteta_agent/response/composer.py
plugins/arteta_agent/trace.py
plugins/arteta_agent/tools/trace.py
plugins/arteta_agent/ui_preferences.py
tests/test_arteta_agent_response.py
tests/test_arteta_chat_commands.py
tests/test_arteta_agent_registry.py
```

### 修改要求

1. 正常群聊默认不追加 `【Agent 调度】`。
2. 恢复并真正使用 Trace 群组白名单；当前全局开关不得忽略白名单。
3. Trace 只在以下情况显示：
   - 用户调用 `/trace` 或询问调用过程；
   - 管理员调试模式；
   - 指定测试群白名单。
4. 显式 Trace 尽量作为独立消息发送，不嵌入正式回复卡片。
5. 删除 `compose_final_response()` 中把 `[grok]` 前缀自动加到正文的行为。
6. `ToolResult.markers` 继续留在结构化 Trace/Audit 中，不直接进入用户正文。
7. 当前信息回答的来源由正文或来源脚注展示，例如：

```text
状态：尚未官宣
来源：Arsenal.com、BBC Sport
我的判断：……
```

而不是显示 `[grok]`。

### 验收

- 普通回复看不到 Agent Trace、参数名和 Marker；
- `/trace` 仍能返回脱敏信息；
- Web 工具 Marker 可在内部 Trace 中查询；
- 正式回复仍能以人类可读方式显示来源。

---

## Phase 7：回复运输方式与图片渲染重构

### 涉及文件

```text
plugins/arteta_chat.py
plugins/arteta_render.py
templates/arteta_render.html
assets/render/situation_room_header.png
tests/test_arteta_render.py
tests/test_arteta_chat_commands.py
```

### 7.1 原生文本与图片选择

新增：

```python
@dataclass(frozen=True)
class ReplyTransportDecision(object):
    mode: str  # "text" or "image"
    reason: str
```

推荐规则：

**优先原生文本：**

- 纯文本少于约 400 字；
- 无公式、代码块、表格、复杂颜色样式；
- 无明确图片渲染请求；
- `casual`、`meme`、短 `football_opinion`。

**使用图片：**

- 长篇结构化分析；
- 公式、代码、表格；
- 多层标题与来源卡片；
- 用户明确要求图片；
- 已产生图片 Artifact。

不要再因为信任度红字或 Trace 样式而强制图片。

### 7.2 模板模式

支持：

```text
compact   短分析卡
full      长分析卡
```

`compact`：

- 隐藏或显著缩小顶部横幅；
- 去掉至少两层装饰边框；
- 减少上下留白；
- 正文字号略大，适合手机阅读；
- 图片高度随内容收缩。

`full`：

- 保留品牌头图但降低高度；
- 一层主边框+一层细强调线即可；
- 支持标题、结论、要点、来源脚注层级；
- Trace 不进入模板。

### 7.3 Markdown 层级

鼓励生成：

```markdown
**结论**
……

**为什么**
- ……
- ……

**消息状态**
尚未官宣；当前为记者消息。
```

模板增加：

```text
lead / section-title / bullet-list / source-note / status-badge
```

### 验收

- 100 字以内普通回复发送文本，不生成 1500px 宽长图；
- 梗图评论可用短文本或 compact 卡；
- 长分析图片不再被顶部横幅和四层边框占据大量空间；
- 手机宽度下正文无需反复放大；
- 现有公式、代码、颜色标签能力不回归。

---

## Phase 8：人格知识的使用边界

### 涉及文件

```text
plugins/arteta_agent/prompts.py
knowledge_base/
tests/test_arteta_prompt_style.py
```

### 修改要求

1. 明确知识库中的经典演讲、阿尔特塔语录和战术概念是“可选素材”，不是每次必须引用。
2. 对 `get_football_knowledge` 返回内容增加写作约束：
   - 不要逐字复述；
   - 同一故事近期已使用则跳过；
   - 只在能解释问题时使用。
3. 不把“像阿尔特塔”简化为高位逼抢、战术板、更衣室三个词。
4. 增加角色内核：控制、标准、细节、责任、保护球员、对传闻谨慎。

### 验收

- 非战术问题不会强行出现战术术语；
- 相同经典故事不会连续复用；
- 角色仍能被识别为阿尔特塔，而不是变成普通助手。

---

## 6. 测试矩阵

| 输入 | 期望模式 | 表情 | 运输方式 | Trace | 信任度显示 |
|---|---|---|---|---|---|
| “早” | casual | 否 | text | 否 | 否 |
| “这图笑死，怎么看”+图片 | meme | 可选 | text/compact | 否 | 否 |
| “罗杰斯适合阿森纳吗” | football_opinion | 通常否 | text | 否 | 否 |
| “萨卡最新伤情怎么样” | current_news | 否 | text/full | 否 | 否 |
| “详细解释阿森纳右路进攻结构” | tactical_deep_dive | 否 | full image | 否 | 否 |
| “你刚才用了什么工具” | serious/debug | 否 | text | 是 | 否 |
| “发个开心表情” | casual | 是 | text+emoji | 否 | 否 |
| 普通梗图分享 | meme | 可选 | text | 否 | 否 |
| 用户辱骂球队成员 | serious | 可选负面 | text | 否 | 仅达到阈值时 |
| 用户等级变化 | 任意 | 按模式 | 按正文 | 否 | 是 |

### 自动测试

必须新增或更新：

```text
tests/test_arteta_agent_response_style.py
tests/test_arteta_agent_mood_response.py
tests/test_arteta_favorability.py
tests/test_arteta_prompt_style.py
tests/test_arteta_agent_response.py
tests/test_arteta_chat_commands.py
tests/test_arteta_render.py
tests/dashboard/test_prompt_service.py
```

### 人工验收

至少生成并检查以下 12 类真实回复：

- 3 条日常闲聊；
- 2 张梗图；
- 2 条球员观点；
- 2 条最新新闻；
- 2 条战术深聊；
- 1 条 Trace 查询。

记录：首句、字数、段落数、表情、图片、Trace、信任度、来源展示。

---

## 7. 提交顺序

每一步独立提交，不要一口气修改全部系统。

```text
1. test: add personality response baseline cases
2. refactor: centralize Arteta persona prompt defaults
3. feat: add response style profiles and dynamic constraints
4. fix: stop forcing neutral mood emojis
5. refactor: decouple favorability from main response generation
6. fix: hide trace and internal markers from normal replies
7. feat: select text or image reply transport by content
8. feat: add compact and full reply card layouts
9. test: add personality and rendering acceptance suite
10. docs: record personality optimization deployment
```

每次提交后执行相关测试；第 9 步再运行全量测试。

---

## 8. 验收标准

本轮完成必须同时满足：

### 人格

- 连续测试中不再出现固定“拍桌子”开场；
- 不以新的动作词替代旧口头禅；
- 梗图、新闻、战术、日常回复明显具有不同节奏；
- 简单问题允许 1～3 句；
- 角色识别度仍然稳定。

### 表情

- 普通中立回复不再强制发表情；
- 强情绪或显式请求仍可发送；
- 表情失败不影响正文。

### 信任度

- 普通交流默认变化为 0；
- 不再出现单次 +93、+346 等随机大幅变化；
- 普通回复不显示“信任度无变化”；
- 主回复 Prompt 不包含好感度 Marker 死命令。

### Trace 与来源

- 普通回复不显示 `【Agent 调度】`、参数名、`[grok]`、`markers:`；
- 显式 Trace 查询仍可工作；
- 最新事实以自然语言展示消息状态和来源。

### 渲染

- 短回复优先原生文本；
- 图片回复支持 compact/full；
- 头图与边框不再压过正文；
- 公式、代码、表格渲染不回归。

### 工程

- Python 3.8 兼容；
- Dashboard 与 QQ 使用同一人格默认值和信任度策略；
- 全量测试通过；
- ECS smoke test 通过；
- Devlog 记录提交、部署版本和人工样例。

---

## 9. 明确不做

本轮禁止顺带进行：

- Web SSRF、Deadline、事实核验算法重写；
- ChromaDB Schema 迁移；
- Agent 权限与 PendingAction 改造；
- 表情包素材大规模重制；
- 历史信任度数据整体重算；
- 完整前端 Dashboard UI 重写。

发现相关问题时记录到后续任务，不扩大本轮范围。

---

## 10. 本地 Agent 执行指令

```text
请先阅读本任务书与当前分支代码，不要直接修改。

第一步：列出实际命中的文件和现有测试，确认 Prompt、表情、信任度、Trace、渲染的真实调用链。
第二步：执行 Phase 0，提交基线测试与当前失败报告。
第三步：严格按 Phase 1→8 的顺序实施，每阶段一个或多个小提交。
第四步：每阶段完成后运行相关测试，不得只依赖手工截图。
第五步：不得顺带修改 Web 安全、ChromaDB、权限模型。
第六步：所有新类型与注解保持 Python 3.8 兼容。
第七步：最终提供：
1. 修改文件清单；
2. 提交哈希；
3. 单元测试与全量测试结果；
4. 12 类人工回复样例；
5. 修改前后截图；
6. ECS 部署和 smoke test 证据；
7. 未解决风险。

遇到计划与当前代码不一致时，先报告差异和建议，不要擅自重写架构。
```
