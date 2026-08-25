# Arteta Bot 可见调试进度与默认长篇回复整合改造计划

**适用分支：** `feat/chromadb-memory`
**代码基线：** 用户上传的最新 `Arteta-bot-feat-chromadb-memory (1).zip`
**目标环境：** Python 3.8、NoneBot2、OneBot V11 / NapCat
**执行对象：** 本地编码 Agent
**任务性质：** 将“可见调试式 ReAct 进度播报”与“短输入也默认充分展开回答”合并为同一实施计划

---

## 0. 本计划的优先级

本计划取代并合并以下两份旧计划中与本任务有关的部分：

- `arteta_agent_react_debug_progress_plan.md`
- `arteta_personality_response_optimization_plan.md`

其中，旧人设计划中的以下规则不再执行：

```text
简单问题允许只回答 1～3 句
casual / meme 默认 short
短回复优先原生文本
梗图默认限制在 120～180 字
输入短时自动选择 compact 回复
```

新的统一规则是：

> **输入长度不能决定回答长度。只要机器人决定回复，就默认给出有结构、有内容、充分展开的回答。**

进度播报仍然采用可见调试模式，直接显示真实工具名，例如 `grok_search`、`web_fetch`、`solve_math_question`，但不展示模型隐藏思维链、完整参数值和工具原始结果。

---

## 1. 需求结论

本轮同时解决两个体验问题。

### 1.1 等待期间没有反馈

当前机器人进入 `run_agent_loop()` 后，模型规划、工具调用、工具回退和最终长回答生成期间都可能保持沉默。群成员容易认为机器人掉线。

目标体验：

```text
[Agent] 正在分析请求并选择可用工具。
[Action] 我将调用 grok_search 实时检索服务，检索最新新闻、官宣和记者原帖。
[Observation] grok_search 调用完成（8.4 秒），已返回可用结果。
[Plan] 当前结果还需要核对原始来源，我将继续执行下一步。
[Action] 我将调用 web_fetch 网页读取服务，读取原始页面正文和发布时间。
[Observation] web_fetch 调用完成（2.1 秒），已返回可用结果。
[Agent] 工具调用已经完成，我将基于现有材料生成一份完整回答。
```

随后发送正式长回答。

### 1.2 短问题被压缩成短答

此前的人设优化方案倾向于：

```text
用户问得短
→ casual / meme
→ 1～3 句
→ 原生短文本
```

用户现在要求恢复原来的“长篇大论”模式。因此目标改为：

```text
用户问得短
→ 仍判断问题类型
→ 默认 expanded / deep 回答
→ 给出结论、理由、背景、例子或影响
→ 根据最终内容决定文本或图片运输方式
```

这里的“长篇”不是机械注水，而是**有信息密度的充分展开**。

---

## 2. 明确要求

1. 等待消息使用 `[Agent]`、`[Plan]`、`[Action]`、`[Observation]`、`[Confirmation]` 等纯文本标签。
2. 不添加图标、emoji 或装饰符号。
3. 直接显示真实注册工具名，例如 `grok_search`、`web_fetch`、`analyze_image`。
4. 当前分支真实工具名为 `grok_search`，不要仅为文案新增 `grok_research` 别名。
5. 数学问题必须显示：

```text
[Action] 我将调用 solve_math_question 数学专用解题 Agent 服务，核对题目条件并完成推导。
```

6. 进度消息必须来自真实 Runtime 事件，不允许 LLM 自己编造调用过程。
7. 不使用 `[Thought]`，不公开隐藏思维链。
8. 不显示参数值、URL 查询参数、用户 ID、群 ID、文件路径、Prompt 或工具原始正文。
9. 最终回答默认充分展开，不因用户输入短而自动缩短。
10. 用户明确要求“简短、一句话、只给答案”时才进入 concise 模式。
11. 进度消息不得写入 ChromaDB、群聊长期记忆、每日消息、信任度计算和最终回复正文。
12. 进度发送失败不得影响正式回答。
13. 正式回答发送前必须关闭所有延迟进度和 heartbeat。
14. 最终 Agent Trace 仍默认隐藏；实时进度播报不等于在最终卡片里追加完整 Trace。

---

## 3. 最终用户体验

### 3.1 最新足球新闻

用户：

```text
罗杰斯到底来不来？
```

进度：

```text
[Agent] 正在分析请求并选择可用工具。
[Action] 我将调用 grok_search 实时检索服务，检索最新新闻、官宣、记者原帖和 X/Twitter 实时线索。
[Observation] grok_search 调用完成（7.9 秒），已返回可用结果。
[Plan] 当前线索还需要核对原始来源，我将继续执行下一步。
[Action] 我将调用 web_fetch 网页读取服务，读取原始页面正文、标题和发布时间。
[Observation] web_fetch 调用完成（2.2 秒），已返回可用结果。
[Agent] 工具调用已经完成，我将按“消息状态、证据强度和个人判断”生成完整回答。
```

最终回答应充分展开，至少包含：

- 当前是否官宣；
- 主要可靠来源说了什么；
- 传闻与事实的边界；
- 对球员适配性的判断；
- 仍存在的不确定性。

### 3.2 数学短题

用户：

```text
x1+2x2+3x3+4x4=13 的正整数解有多少？
```

进度：

```text
[Agent] 正在分析题目并选择解题服务。
[Action] 我将调用 solve_math_question 数学专用解题 Agent 服务，核对题目条件并完成推导。
[Observation] solve_math_question 调用完成（4.7 秒），已返回可用结果。
[Agent] 解题结果已经返回，我将补全思路、步骤、验证和最终答案。
```

最终回答不能只返回数字，应默认包含：

- 正整数向非负整数的变量代换；
- 采用的计数方法；
- 关键枚举或生成函数步骤；
- 最终答案；
- 必要的结果校验。

### 3.3 图片或梗图

用户：

```text
这图什么意思？
```

进度：

```text
[Action] 我将调用 analyze_image 视觉识别 Agent 服务，读取图片中的文字、对象和关键信息。
[Observation] analyze_image 调用完成（5.8 秒），已返回可用结果。
[Agent] 图片内容已经识别完成，我将从画面信息、梗点和足球语境三个层面展开说明。
```

最终回答可以有活力，但不再限制为一两句。应说明：

- 图片直观内容；
- 笑点或反差；
- 相关足球背景；
- 一段自然的角色化点评。

### 3.4 无工具但生成较慢

```text
[Agent] 正在分析请求并组织一份完整回答。
```

若最终生成持续较久：

```text
[Agent] 详细回答仍在生成，我正在整理结构、论据和排版。
```

---

## 4. 总体架构

```text
QQ 消息
   ↓
Activation / Routing / Planning
   ↓
AgentRuntimeRunner
   ├─ 产生结构化 ProgressEvent
   ├─ 执行真实工具
   ├─ 收集 ToolResult
   └─ 进入最终回答生成
           ↓
DebugProgressReporter
   ├─ 延迟发送
   ├─ 节流、合并、去重
   ├─ 显示真实工具名
   └─ 不进入 AgentState
           ↓
LongFormResponsePolicy
   ├─ 默认 expanded
   ├─ 根据场景规定回答结构
   ├─ 用户明确要求时才 concise
   └─ 决定最终文本/图片运输方式
           ↓
正式回复
```

新增或扩展目录：

```text
plugins/arteta_agent/
├── progress/
│   ├── __init__.py
│   ├── models.py
│   ├── formatter.py
│   ├── reporter.py
│   └── policy.py
└── response/
    ├── style.py
    ├── length_policy.py
    ├── composer.py
    └── transport.py
```

---

## 5. 可见调试式 ReAct 协议

### 5.1 允许的标签

| 标签 | 用途 | 示例 |
|---|---|---|
| `[Agent]` | 请求处理、长时间等待、最终生成 | `[Agent] 正在分析请求并组织一份完整回答。` |
| `[Plan]` | 公开的高层下一步状态 | `[Plan] 当前结果还需要核对原始来源，我将继续执行下一步。` |
| `[Action]` | 即将真实调用工具 | `[Action] 我将调用 web_fetch 网页读取服务，读取原始页面。` |
| `[Observation]` | 工具状态摘要 | `[Observation] web_fetch 调用完成（2.1 秒），已返回可用结果。` |
| `[Confirmation]` | 等待权限或确认 | `[Confirmation] mute_member 需要管理员权限和二次确认，当前尚未执行。` |

禁止：

```text
[Thought]
内部分析：
我认为用户真正想问的是……
我选择这个工具是因为模型内部推理认为……
```

### 5.2 标准事件序列

无工具慢回复：

```text
run_started
model_round_started
final_synthesis_started
finished
```

单工具：

```text
run_started
model_round_started
tool_batch_started
tool_batch_finished
final_synthesis_started
finished
```

多工具：

```text
run_started
model_round_started
tool_batch_started
tool_batch_finished
model_round_started
tool_batch_started
tool_batch_finished
final_synthesis_started
finished
```

新增最终生成阶段事件：

```text
final_synthesis_started
final_synthesis_heartbeat
```

这是本整合计划相对于旧进度计划的重要增量，因为默认长篇回答会让**工具结束后的生成阶段**也产生明显等待。

---

## 6. Progress 事件模型

新建 `plugins/arteta_agent/progress/models.py`：

```python
from dataclasses import dataclass, field
from typing import Dict, List


PROGRESS_RUN_STARTED = "run_started"
PROGRESS_MODEL_ROUND_STARTED = "model_round_started"
PROGRESS_TOOL_BATCH_STARTED = "tool_batch_started"
PROGRESS_TOOL_FINISHED = "tool_finished"
PROGRESS_TOOL_BATCH_FINISHED = "tool_batch_finished"
PROGRESS_WAITING_CONFIRMATION = "waiting_confirmation"
PROGRESS_FINAL_SYNTHESIS_STARTED = "final_synthesis_started"
PROGRESS_FINAL_SYNTHESIS_HEARTBEAT = "final_synthesis_heartbeat"
PROGRESS_RUNTIME_STOPPED = "runtime_stopped"
PROGRESS_FINISHED = "finished"


@dataclass(frozen=True)
class ProgressToolCall(object):
    call_id: str
    name: str
    permission: str = ""
    attempt: int = 1
    argument_keys: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentProgressEvent(object):
    kind: str
    round_index: int = 0
    tools: List[ProgressToolCall] = field(default_factory=list)
    status: str = ""
    duration_ms: int = 0
    error_code: str = ""
    metadata: Dict[str, object] = field(default_factory=dict)
```

事件中不得包含：

- 完整工具参数；
- ToolResult 正文；
- 模型消息正文；
- Prompt；
- 密钥；
- URL 查询参数；
- 用户、群、消息 ID；
- 本地文件绝对路径。

---

## 7. Runtime 插入点

修改 `plugins/arteta_agent/runtime/runner.py`。

### 7.1 Observer 接口

```python
ProgressObserver = Callable[[AgentProgressEvent, AgentState], object]
```

`AgentRuntimeRunner.__init__()` 增加：

```python
progress_observer: Optional[ProgressObserver] = None
```

统一发送方法：

```python
async def _emit_progress(self, event, state):
    if not self.progress_observer:
        return
    try:
        await _maybe_await(self.progress_observer(event, state))
    except Exception:
        LOGGER.warning("agent_progress_observer_failed", exc_info=True)
```

进度失败不得中断主任务。

### 7.2 插入事件

1. `_run_impl()` 开始：`run_started`。
2. 每次调用模型前：`model_round_started`。
3. 真实调用 `tool_executor()` 前：`tool_batch_started`。
4. 工具返回后：`tool_finished` 或 `tool_batch_finished`。
5. `permission_required`：`waiting_confirmation`。
6. 进入最终 LLM 组织回答前：`final_synthesis_started`。
7. 最终生成持续超过阈值：Reporter 本地触发 `final_synthesis_heartbeat`。
8. Runtime 超时或 Guard 停止：`runtime_stopped`。
9. 正式结果准备完成：`finished`。

### 7.3 并行工具

并行安全读取工具必须合并：

```text
[Action] 我将并行调用 get_arsenal_result、get_pl_table 和 get_arsenal_injuries 服务，核对赛果、积分榜和伤病信息。
[Observation] 并行工具调用完成：3 个成功，0 个失败，用时 4.8 秒。
```

禁止为同一批三个工具连续发送三条 Action 和三条 Observation。

---

## 8. ToolSpec 进度元数据

新建：

```python
@dataclass(frozen=True)
class ToolProgressSpec(object):
    service_type: str
    action_purpose: str
    visibility: str = "normal"
    synthesis_hint: str = ""
```

`visibility`：

```text
normal
slow_only
silent
```

扩展 `ToolSpec`：

```python
progress: Optional[ToolProgressSpec] = None
```

约束：

- `build_openai_tools()` 不向模型暴露 `progress` 元数据；
- 没有元数据的工具使用通用文案；
- 新工具注册时应同步配置进度说明；
- 不维护一套完全脱离 Registry 的巨大工具名判断链。

---

## 9. 工具文案目录

标准模板：

```text
[Action] 我将调用 {tool_name} {service_type}，{action_purpose}。
```

### 9.1 Web 与实时信息

| 工具名 | 服务类型 | Action 用途 |
|---|---|---|
| `grok_search` | 实时检索服务 | 检索最新新闻、官宣、记者原帖和 X/Twitter 实时线索 |
| `web_search` | 公网搜索服务 | 搜索公开网页来源并筛选可继续核对的结果 |
| `web_fetch` | 网页读取服务 | 读取原始页面正文、标题和发布时间 |
| `verify_recent_claim` | 近期事实核验服务 | 交叉核对近期说法、来源强度和证据状态 |
| `fetch_x_post` | X 原帖读取服务 | 读取 X/Twitter 原帖、作者和发布时间 |
| `analyze_links` | 链接分析服务 | 打开消息中的链接并提取页面关键信息 |
| `search_news` | 足球新闻搜索服务 | 搜索足球、转会和阿森纳相关的最新公开消息 |
| `search_football_news` | 本地足球新闻库服务 | 检索最近收录的联赛、欧冠和足球新闻 |

### 9.2 足球数据与知识

| 工具名 | 服务类型 | Action 用途 |
|---|---|---|
| `get_arsenal_result` | 阿森纳比赛数据服务 | 获取最近比赛的对手、比分和赛事信息 |
| `get_pl_table` | 英超积分榜数据服务 | 获取当前排名、积分和分差 |
| `get_arsenal_injuries` | 阿森纳伤病数据服务 | 核对当前伤病名单和复出信息 |
| `get_football_knowledge` | 足球战术知识库服务 | 查询战术概念、历史资料和阿尔特塔相关知识 |

### 9.3 数学、算法、代码与理科

| 工具名 | 服务类型 | Action 用途 |
|---|---|---|
| `solve_math_question` | 数学专用解题 Agent 服务 | 核对题目条件并完成推导 |
| `solve_algorithm_problem` | 算法专用解题 Agent 服务 | 分析状态设计、转移关系和时间复杂度 |
| `solve_code_question` | 代码专用分析 Agent 服务 | 检查代码逻辑、错误原因和边界情况 |
| `solve_science_question` | 理科综合解题 Agent 服务 | 建立计算模型并核对公式和结果 |

### 9.4 图片、文档、生成与渲染

| 工具名 | 服务类型 | Action 用途 |
|---|---|---|
| `analyze_image` | 视觉识别 Agent 服务 | 读取图片中的文字、对象和关键信息 |
| `read_document` | 文档阅读 Agent 服务 | 读取 PDF 或 DOCX 并定位与问题相关的内容 |
| `generate_image` | 图像生成服务 | 根据用户描述生成图片 artifact |
| `render_markdown_to_image` | Markdown 与公式渲染服务 | 将公式、代码或结构化内容排版成图片 |
| `render_text_to_tactical_board` | 战术板渲染服务 | 将普通文本排版成战术板风格图片 |

### 9.5 群聊记忆与消息检索

| 工具名 | 服务类型 | Action 用途 |
|---|---|---|
| `query_group_memory` | 群聊长期记忆检索服务 | 按语义查找本群保存的历史对话 |
| `get_recent_group_context` | 近期群聊上下文服务 | 回看最近聊天并解析“刚才、他们、那件事”等指代 |
| `find_recent_messages_by_alias` | 群成员发言检索服务 | 根据昵称或别名查找成员最近发言 |
| `search_daily_messages` | 每日消息记录检索服务 | 查找指定日期或关键词附近的群聊消息 |
| `remember_user_preference` | 用户长期偏好记忆服务 | 保存用户明确要求以后持续生效的偏好 |
| `clear_group_memory` | 群聊记忆清理服务 | 准备清空群聊长期记忆，执行前等待确认 |

### 9.6 群成员、总结、行为和调试

| 工具名 | 服务类型 | Action 用途 | 可见性 |
|---|---|---|---|
| `get_group_members` | 群成员数据服务 | 获取近期活跃群成员名单 | normal |
| `get_member_relations` | 群内互动关系服务 | 汇总指定成员最近的互动关系 | normal |
| `get_user_profile` | 群成员档案服务 | 读取指定成员的公开群内档案和最近发言 | normal |
| `get_current_user_profile` | 当前用户档案服务 | 读取当前提问者在本群保存的档案 | slow_only |
| `generate_today_group_summary` | 今日群聊总结 Agent 服务 | 汇总当天主要话题和关键事件 | normal |
| `generate_weekly_report` | 阿森纳周报生成 Agent 服务 | 根据文章资料生成结构化周报 | normal |
| `show_behavior_policy` | 行为策略读取服务 | 读取当前群已生效的软行为设置 | slow_only |
| `update_behavior_policy` | 行为策略更新服务 | 更新当前群的回复偏好 | slow_only |
| `update_ui_preference` | UI 偏好更新服务 | 调整受控的字体、颜色或排版设置 | slow_only |
| `show_agent_trace` | Agent Trace 服务 | 生成本次请求的脱敏调用记录 | slow_only |
| `send_mood_emoji` | 表情发送服务 | 发送匹配情绪的白名单表情 | silent |

### 9.7 写操作与管理员工具

未确认前不得声称已执行：

```text
[Action] Agent 请求调用 mute_member 群成员禁言服务。
[Confirmation] mute_member 需要管理员权限和二次确认，当前尚未执行。
```

适用：

- `send_like`
- `send_group_message`
- `clear_group_memory`
- `mute_member`
- `delete_message`
- `update_config`
- `update_favor`
- `update_user_profile_by_llm`

---

## 10. Observation 文案

成功：

```text
[Observation] {tool_name} 调用完成（{duration} 秒），已返回可用结果。
```

成功但无有效内容：

```text
[Observation] {tool_name} 调用完成（{duration} 秒），但没有返回可用结果。
```

超时：

```text
[Observation] {tool_name} 调用超时（{duration} 秒），未获得可用结果。
```

不可用：

```text
[Observation] {tool_name} 当前不可用，Agent 将根据现有计划决定是否继续。
```

错误：

```text
[Observation] {tool_name} 调用失败（{safe_error_code}），未获得可用结果。
```

允许直接展示的错误码：

```text
TimeoutError
Unavailable
InvalidArguments
PermissionRequired
UnsafeURL
ResponseTooLarge
UnsupportedContentType
```

其他统一为 `ToolError`。不得输出 `str(exc)`。

---

## 11. 默认长篇回答策略

新建 `plugins/arteta_agent/response/length_policy.py`。

### 11.1 核心模型

```python
from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class LongFormResponsePolicy(object):
    mode: str = "expanded"  # concise / expanded / deep
    minimum_sections: int = 3
    target_min_chars: int = 350
    target_max_chars: int = 900
    include_direct_answer: bool = True
    include_reasoning_summary: bool = True
    include_context_or_example: bool = True
    include_caveats: bool = False
    reason_codes: List[str] = field(default_factory=list)
```

不要把 `mode` 绑定到用户输入长度。

### 11.2 模式选择

默认：

```text
expanded
```

进入 `deep`：

- 用户要求“详细、全面、展开、深入”；
- 战术、数学、算法、代码、物理等需要完整推导；
- 多来源新闻核验；
- 文档总结或复杂图片分析；
- 需要比较多个方案。

进入 `concise`：

- 用户明确要求“简单点、简短、一句话、只要答案”；
- 纯确认“收到/好的/是否执行”；
- PermissionRequired；
- 错误和不可用提示；
- `[NO_REPLY]`；
- 安全拒绝；
- 工具进度消息本身。

### 11.3 推荐长度

| 场景 | 默认模式 | 建议中文字符 | 结构 |
|---|---|---:|---|
| 日常短问、问候、简单观点 | expanded | 250～500 | 回应、展开、自然收束 |
| 梗图或短图片问题 | expanded | 300～600 | 画面、梗点、背景、点评 |
| 足球球员或阵容观点 | expanded | 500～900 | 结论、优点、风险、适配、判断 |
| 最新新闻、转会、伤病 | expanded/deep | 500～1000 | 状态、来源、分析、不确定性 |
| 战术深聊 | deep | 800～1600 | 结论、机制、例子、优缺点、影响 |
| 数学、算法、代码、理科 | deep | 按题目需要 | 方法、步骤、验证、答案 |
| 群聊记忆总结 | expanded | 400～900 | 找到的内容、上下文、结论 |
| 用户明确要求简短 | concise | 50～250 | 直接答案为主 |

字符数用于软约束，不得为了达标重复同义句。

### 11.4 “长篇”质量要求

每个 expanded/deep 回答至少包含以下三项：

1. **直接回答。** 第一段明确给出判断或结论。
2. **充分展开。** 解释原因、依据或过程。
3. **补充价值。** 给出背景、例子、影响、风险或校验。

不允许用以下方式虚假拉长：

- 重复同一结论；
- 连续使用“换句话说”；
- 堆砌阿尔特塔、战术板、更衣室等人设词；
- 无关的背景科普；
- 为了段落数拆碎完整句子。

---

## 12. 场景化长回答结构

修改 `plugins/arteta_agent/response/style.py`，保留场景识别，但不再将 `casual`、`meme` 映射为 `short`。

### 12.1 日常短问

默认结构：

```text
第一段：直接回应用户
第二段：说明原因或展开观点
第三段：补充一个相关观察或实际影响
```

### 12.2 梗图

默认结构：

```text
画面在说什么
真正的笑点和反差
相关足球背景
一段自然的人格化点评
```

仍要避免把梗图写成无休止的战术论文，但不再限制为一两句。

### 12.3 足球观点

```text
明确结论
适合的部分
不适合或风险
放进阿森纳体系后的具体位置
最终判断
```

### 12.4 当前新闻

```text
目前状态
已经确认的事实
仍是传闻的部分
来源强度
对球队或球员的影响
个人判断与不确定性
```

### 12.5 数学与代码

```text
题意和目标
采用的方法
关键步骤
结果验证
最终答案
```

### 12.6 严肃与技术问题

长篇不等于角色表演。技术、隐私、权限和错误场景应降低人设强度，以清楚准确为主。

---

## 13. Prompt 修改

统一默认 Prompt 来源仍放在 `plugins/arteta_agent/prompts.py`。

### 13.1 删除旧短答规则

删除或覆盖：

```text
简单问题可以只回答 1～3 句
梗图控制在 120 字以内
普通短聊天优先短答
用户输入短则简短回应
```

### 13.2 新增长期规则

```text
- 除非用户明确要求简短，否则默认充分展开回答。
- 用户消息很短不代表问题简单，也不代表回答必须短。
- 默认先给直接结论，再解释理由，并补充背景、例子、影响或验证。
- 长回答必须增加有效信息，不要重复同义句凑长度。
- 梗图和日常问题也应完整回应，但保持自然，不强行写成正式论文。
- 数学、算法、代码和理科问题默认给出方法、关键步骤、校验与最终答案。
- 最新新闻默认区分已确认事实、媒体消息和个人判断。
- 不描述“拍桌子、敲战术板、摊手、推门”等自身动作作为固定开场。
```

### 13.3 本轮动态风格块

示例：

```text
【本轮回答模式：expanded】
- 用户输入较短，但本轮仍需充分展开。
- 第一部分直接回答，随后解释原因，并补充背景或影响。
- 建议 3～6 个自然段；不重复同义内容。
- 保持阿尔特塔人格，但不要堆砌动作描写和战术口头禅。
```

数学：

```text
【本轮回答模式：deep / mathematical】
- 给出完整方法、关键推导、结果校验和最终答案。
- 不只返回工具结论。
- 可以省略机械计算，但不能跳过关键逻辑。
```

---

## 14. 最终生成阶段的进度播报

由于默认长篇回答，工具完成之后还可能等待较久。必须增加 synthesis 阶段。

### 14.1 开始生成

有工具：

```text
[Agent] 工具调用已经完成，我将基于现有结果生成一份完整回答。
```

足球新闻：

```text
[Agent] 工具调用已经完成，我将按消息状态、来源强度和影响分析生成完整回答。
```

数学：

```text
[Agent] 解题结果已经返回，我将补全方法、关键步骤、验证和最终答案。
```

图片：

```text
[Agent] 图片内容已经识别完成，我将从画面信息、背景和核心含义三个层面展开说明。
```

### 14.2 生成 heartbeat

最终生成超过 10～12 秒，最多发送一次：

```text
[Agent] 详细回答仍在生成，我正在整理结构、论据和排版。
```

不得每 10 秒重复刷屏。

### 14.3 完成前关闭

正式回复发送前：

```python
await progress_reporter.close()
```

`close()` 必须：

- 取消首条延迟任务；
- 取消工具 heartbeat；
- 取消 synthesis heartbeat；
- 等待发送锁释放；
- 标记 Reporter closed；
- 确保之后任何事件都不再发送。

---

## 15. DebugProgressReporter

默认配置建议：

```text
initial_delay_seconds = 0.8
minimum_update_interval_seconds = 1.8
tool_heartbeat_seconds = 12.0
synthesis_heartbeat_seconds = 10.0
maximum_messages = 9
maximum_tool_heartbeats = 1
maximum_synthesis_heartbeats = 1
```

规则：

1. 0.8 秒内完成的请求不发进度。
2. 首条延迟期间只保留最新、最有价值的事件。
3. 同一文案去重。
4. 并行工具合并。
5. 工具和 synthesis heartbeat 各最多一次。
6. 最多 9 条进度。
7. 正式回复前关闭。
8. 进度发送错误只写脱敏日志。
9. 进度消息不追加到 `state.messages`。
10. 进度消息不触发表情、信任度、图片渲染和记忆写入。

事件优先级：

```text
Confirmation
> Tool failure
> Tool action
> Tool observation
> Final synthesis started
> Plan
> Agent heartbeat
```

---

## 16. 文本与图片运输方式

旧计划中“短输入优先文本”必须删除。运输方式只看**最终输出内容**和用户偏好。

### 16.1 决策规则

原生文本：

- 最终回答结构简单且长度较短；
- 无公式、代码块、表格；
- 用户明确要求文本；
- 平台图片渲染不可用。

图片或 full 卡片：

- 最终回答较长；
- 有多个标题、列表、来源；
- 数学公式、代码、表格；
- 新闻来源卡；
- 用户明确要求图文排版。

关键要求：

```text
输入只有几个字
≠ 强制 text
≠ 强制 compact
```

建议第一版：

```text
最终纯文本少于 350 字且无复杂结构 → text
350～700 字或有 2 个以上结构标题 → compact/full 由模板判断
超过 700 字、含公式/代码/表格 → full image
```

由于默认长篇模式，许多短问题最终会自然进入 full 卡片，这是预期行为。

### 16.2 Progress 与最终渲染分离

进度消息始终是 QQ 原生纯文本，不进入最终图片。

最终卡片不得附加：

- `[Action]`；
- `[Observation]`；
- 完整调用耗时；
- `markers:[grok]`；
- Agent Trace 参数。

用户主动查询 Trace 时另行发送脱敏记录。

---

## 17. Behavior Policy 与配置

允许 `progress.` 和 `reply.` 前缀。

### 17.1 Progress 策略

| 键 | 默认值 | 含义 |
|---|---:|---|
| `progress.enabled` | `true` | 是否显示等待进度 |
| `progress.mode` | `react_debug` | 可见调试模式 |
| `progress.show_tool_names` | `true` | 显示真实工具名 |
| `progress.show_observations` | `true` | 显示完成状态 |
| `progress.show_duration` | `true` | 显示安全耗时 |
| `progress.show_argument_keys` | `false` | 默认不显示参数键 |

### 17.2 Reply 策略

| 键 | 默认值 | 含义 |
|---|---:|---|
| `reply.default_detail_mode` | `expanded` | 默认充分展开 |
| `reply.short_input_long_answer` | `true` | 短输入不触发短答 |
| `reply.allow_user_concise_override` | `true` | 用户可要求简短 |
| `reply.expanded_min_chars` | `350` | expanded 软下限 |
| `reply.expanded_max_chars` | `900` | expanded 软上限 |
| `reply.deep_max_chars` | `1600` | deep 软上限 |

第一版不允许普通聊天直接任意修改数值，只允许：

```text
reply.default_detail_mode
reply.short_input_long_answer
progress.enabled
progress.mode
progress.show_observations
```

时间、字数和消息数由环境变量或管理员配置控制。

环境变量：

```text
ARTETA_AGENT_PROGRESS_ENABLED=true
ARTETA_AGENT_PROGRESS_MODE=react_debug
ARTETA_AGENT_PROGRESS_INITIAL_DELAY=0.8
ARTETA_AGENT_PROGRESS_MIN_INTERVAL=1.8
ARTETA_AGENT_PROGRESS_HEARTBEAT=12.0
ARTETA_AGENT_SYNTHESIS_HEARTBEAT=10.0
ARTETA_AGENT_PROGRESS_MAX_MESSAGES=9
ARTETA_REPLY_DEFAULT_DETAIL_MODE=expanded
ARTETA_REPLY_SHORT_INPUT_LONG_ANSWER=true
ARTETA_REPLY_EXPANDED_MIN_CHARS=350
ARTETA_REPLY_EXPANDED_MAX_CHARS=900
ARTETA_REPLY_DEEP_MAX_CHARS=1600
```

优先级：

```text
用户本轮明确要求
> 群 Behavior Policy
> 环境变量
> 代码默认值
```

---

## 18. 调用链改造

显式传递 Observer，不塞进 `ctx.extra`。

```text
arteta_chat.py
→ run_agent_loop(progress_observer=...)
→ AgentRequest.progress_observer
→ run_agent_request
→ run_runtime_loop_from_state
→ AgentRuntimeRunner(progress_observer=...)
```

长回答策略：

```text
arteta_chat.py / request builder
→ classify_response_style(...)
→ resolve_long_form_policy(...)
→ build_dynamic_response_constraints(...)
→ model_call / finalizer
→ transport decision
```

必须保证：

- 初始计划工具路径有进度；
- 模型后续工具路径有进度；
- Required Tool 路径有进度；
- 无工具慢回复有 synthesis 提示；
- Timeout、Exception、NO_REPLY、PermissionRequired 所有退出路径都关闭 Reporter。

---

## 19. 与人设、表情、信任度和 Trace 的边界

### 19.1 人设

长篇模式不恢复“拍桌子”等固定动作。

继续保留：

```text
不固定使用拍桌子、敲战术板、摊手、推门等动作开场
不为凑长度堆砌更衣室、高位逼抢和战术板
根据问题类型控制人格强度
```

### 19.2 表情

Progress 不触发 `send_mood_emoji`。

普通最终回复仍不应因为“非负面”而强制发表情。长篇模式与表情策略互不绑定。

### 19.3 信任度

Progress 消息不参与信任度；最终长篇回答不应包含强制好感度 Marker。

### 19.4 Trace

实时调试进度默认显示，但最终回复卡片不追加完整 Trace。

区别：

```text
实时进度：本次执行过程中分阶段显示少量状态
完整 Trace：用户主动要求时返回脱敏调用记录
```

---

## 20. 测试计划

新增或更新：

```text
tests/test_arteta_agent_progress_models.py
tests/test_arteta_agent_progress_formatter.py
tests/test_arteta_agent_progress_reporter.py
tests/test_arteta_agent_runtime_progress.py
tests/test_arteta_agent_long_form_policy.py
tests/test_arteta_agent_response_style.py
tests/test_arteta_agent_prompt_length.py
tests/test_arteta_chat_progress.py
tests/test_arteta_reply_transport.py
```

### 20.1 Progress Formatter

覆盖：

- `grok_search` 显示真实工具名；
- `solve_math_question` 显示“数学专用解题 Agent 服务”；
- 不含 emoji；
- 不出现 `[Thought]`；
- Observation 带安全耗时；
- 错误码白名单；
- `send_mood_emoji` 静默；
- confirm/admin 不声称已执行；
- synthesis 文案按数学、新闻、图片场景变化。

### 20.2 Reporter

覆盖：

1. 0.8 秒内完成发送 0 条；
2. 首条优先 Action；
3. 文案去重；
4. 最小间隔；
5. 最大 9 条；
6. 工具 heartbeat 一次；
7. synthesis heartbeat 一次；
8. 工具完成取消 heartbeat；
9. `close()` 后无消息；
10. send 抛错不影响主结果；
11. 并行工具合并；
12. 不保存 ToolResult 正文。

### 20.3 Long-form Policy

必须覆盖：

| 输入 | 预期模式 | 说明 |
|---|---|---|
| `早` | expanded | 短输入不自动 concise |
| `这图什么意思` + 图片 | expanded | 图片解释充分展开 |
| `罗杰斯适合吗` | expanded | 给出体系适配分析 |
| `萨卡伤了吗` | expanded | 搜索后给状态、来源和影响 |
| `只告诉我答案` + 数学题 | concise | 尊重用户明确要求 |
| `详细讲讲` + 战术问题 | deep | 完整展开 |
| PermissionRequired | concise | 仅说明确认状态 |
| 工具失败 | concise/controlled | 不写长篇空话 |

断言：

- 输入长度不参与 concise 判定；
- `casual`、`meme` 不再默认 `short`；
- 用户明确简短要求优先级最高；
- 生成 Prompt 包含 expanded/deep 结构要求；
- 不出现固定动作开场要求。

### 20.4 端到端手工验收

至少测试：

1. 一个字问候；
2. 五字足球观点；
3. 图片+“啥意思”；
4. 最新伤病；
5. 转会新闻；
6. 数学短题；
7. 算法题；
8. 文档总结；
9. 群聊记忆；
10. 用户明确要求简短；
11. 工具超时回退；
12. 管理员确认工具。

每条记录：

- Progress 消息序列；
- 工具真实调用顺序；
- 最终回答字数和结构；
- 是否重复或注水；
- 是否出现内部参数；
- 是否正确关闭 Reporter；
- 最终文本/图片运输方式。

---

## 21. 建议提交顺序

每一步单独提交，不要一次性混合。

```text
1. test: add progress and long-form response baselines
2. feat: add progress event models and ToolSpec metadata
3. feat: emit runtime progress events
4. feat: add debug progress formatter and QQ reporter
5. feat: add final synthesis progress events
6. feat: add expanded long-form response policy
7. refactor: update prompt and response style length rules
8. feat: select reply transport from final output instead of input length
9. feat: add progress and reply behavior policies
10. test: add end-to-end progress and long-form acceptance suite
11. docs: record deployment and smoke results
```

禁止将全部改动压成一个提交。

每个提交执行：

```text
compile / static check
→ 定向 pytest
→ git diff
→ 人工审查
```

最后执行全量测试与 ECS smoke。

---

## 22. 验收标准

### 22.1 Progress

- 长任务等待期间有真实状态；
- 显示实际工具名；
- 数学工具显示专用 Agent 服务文案；
- 无 emoji；
- 无 `[Thought]`；
- 不泄露参数值、原始结果和异常详情；
- 并行工具合并；
- 快速请求不闪现提示；
- 正式回复后不再出现迟到的 Progress。

### 22.2 长篇回答

- 短输入不再自动短答；
- `早`、`这图什么意思`、`罗杰斯适合吗` 等输入默认 expanded；
- 足球观点包含结论、理由、风险和适配；
- 新闻包含状态、来源、影响和不确定性；
- 数学包含方法、关键步骤、验证和答案；
- 长篇不通过重复和人设口头禅注水；
- 用户明确要求简短时能切换 concise。

### 22.3 工程

- Python 3.8 兼容；
- Progress 不进入 AgentState、Memory、信任度和最终正文；
- Progress 失败不影响主流程；
- Dashboard 与 QQ 读取同一默认回复长度策略；
- 全量测试通过；
- ECS smoke 通过；
- 提供提交哈希、测试日志、样例截图和未解决风险。

---

## 23. 明确不做

本轮禁止顺带处理：

- Web SSRF、Canonical、事实核验算法；
- ChromaDB Schema；
- PendingAction 权限模型重写；
- 表情素材重制；
- 历史信任度重算；
- Dashboard 大规模 UI 重构；
- 真实工具名批量重命名；
- 将隐藏思维链暴露给用户。

发现相关问题只记录，不扩大范围。

---

## 24. 本地 Agent 执行指令

```text
请在 feat/chromadb-memory 分支执行本任务。

一、开始前
1. 阅读本计划和当前代码。
2. 确认真实 Runtime、ToolSpec、AgentRequest、arteta_chat 消息发送和最终 Prompt 构建链路。
3. 列出与计划不一致的实际文件和接口。
4. 不要直接开始大规模重构。

二、实现顺序
1. 先添加失败的 Progress 与长篇回复基线测试。
2. 按提交顺序完成 ProgressEvent、Runtime 事件、Reporter 和 ToolSpec 元数据。
3. 增加 final_synthesis_started 与 synthesis heartbeat。
4. 新增 LongFormResponsePolicy，并将默认值设为 expanded。
5. 删除“短输入自动短答”“casual/meme 默认 short”等旧规则。
6. 保留用户明确 concise 覆盖与权限/错误等必要短答例外。
7. 最后调整运输方式：只根据最终内容决定 text/full image，不根据输入长度决定。

三、硬限制
1. 不输出隐藏思维链。
2. 不显示工具参数值、ToolResult 正文、原始异常、ID、密钥和文件路径。
3. Progress 不进入 Memory、信任度、图片渲染和最终正文。
4. 进度失败不得影响正式回复。
5. 所有类型注解保持 Python 3.8 兼容。
6. 不修改 Web 安全、ChromaDB 和权限模型。
7. 每阶段小提交，不得 squash 为单个巨型提交。

四、每阶段检查
1. py_compile 或项目静态检查。
2. 定向 pytest。
3. git diff --check。
4. 人工查看 Progress 文案和最终回复样例。

五、最终交付
1. 修改文件清单。
2. 每个提交哈希和目的。
3. 定向测试和全量测试原始结果。
4. 至少 12 个端到端样例，包含 Progress 序列和最终回答。
5. 修改前后截图。
6. ECS 部署版本和 smoke test 结果。
7. 未完成项和残余风险。

遇到计划与当前架构不一致时，先输出差异报告和最小调整建议，不要擅自另起一套架构。
```
