# QQ Agent 项目重构 Spec / Plan

## 0. 背景与目标

当前 Arteta Bot 已具备主聊天、Function Calling、ChromaDB 记忆、画像、图片识别、渲染、日报/周报、Dashboard、验证脚本等能力。但这些能力目前分散在多个固定命令与插件中，主对话链路只能调用少数查询型工具，整体仍偏“命令机器人”，不是统一自主 agent。

本次重构目标不是推翻现有项目，而是在现有项目上新增一层统一 Agent Tool System，使自然语言对话可以自主调用工具、组合能力、管理权限、执行观察循环，并逐步替代固定命令入口。

核心目标：

1. 保留现有 NoneBot 插件、数据库、渲染、记忆、画像、日报、周报等模块。
2. 新增统一工具注册中心 Tool Registry，避免 `TOOLS` 与 `execute_tool_call()` 双处硬编码。
3. 新增 ToolContext，统一向工具传入 `bot/event/group_id/user_id/nickname/raw_message/reply/image/context`。
4. 新增权限层，将工具分为只读、低风险写入、需确认写入、管理员操作。
5. 新增 Agent Executor，让主聊天链路可以调用更多工具，而不只查足球数据。
6. 逐步把现有命令功能封装为 agent tool，保留旧命令作为兼容入口。
7. 加入测试与验证脚本，确保每阶段可回滚、可验收。

## 1. 当前问题判断

### 1.1 主链路已有 Function Calling，但范围较窄

当前 `arteta_tools.py` 已有 DeepSeek Function Calling 调用逻辑，使用 `tools: TOOLS` 和 `tool_choice: "auto"`，并通过 `run_tool_loop()` 最多执行 5 轮工具调用。

但目前工具主要是查询型：

- get_arsenal_result
- get_pl_table
- get_arsenal_injuries
- search_news
- get_football_knowledge
- get_group_members
- get_member_relations

问题：这些工具不能覆盖画图、日报、周报、画像、档案、排行榜、点赞、禁言、清除记忆、验证脚本、日志、配置管理等项目已有能力。

### 1.2 大量能力仍是固定命令

`arteta_chat.py` 和其他插件中存在大量固定命令：

- A / 塔子 / 阿尔特塔
- 算法 / 数学 / 物理 / 代码
- 盒
- 好感度
- 好感度排行
- 刷新情报
- clear / 清除记忆
- 档案 / profile
- 赞我
- 画图
- 今日总结
- 周报
- 发誓

这些能力需要用户记住命令触发，LLM 无法在普通对话中主动选择调用。

### 1.3 工具执行器不利于扩展

当前工具执行器采用：

```python
if name == "get_arsenal_result":
    ...
elif name == "get_pl_table":
    ...
```

问题：

1. 工具定义和执行逻辑分离维护，容易不同步。
2. 缺少参数校验。
3. 缺少权限等级。
4. 缺少统一日志。
5. 缺少 tool metadata。
6. 缺少可观测性与回归测试入口。

### 1.4 Agent 缺少权限控制

如果未来让 LLM 调用点赞、禁言、清除记忆、改配置、跑验证脚本等工具，必须有权限层。

建议分级：

| 权限等级 | 含义 | 是否可自动执行 |
|---|---|---|
| safe_read | 只读查询 | 是 |
| safe_write | 低风险写入/生成 | 大多数情况可直接执行 |
| confirm_write | 会改变用户/群状态 | 需要用户确认 |
| admin_action | 管理员或系统级操作 | 仅管理员 + 二次确认 |

## 2. 新架构设计

### 2.1 目录结构

新增目录：

```text
plugins/
  arteta_agent/
    __init__.py
    context.py
    registry.py
    permissions.py
    schemas.py
    executor.py
    planner.py
    prompts.py
    errors.py
    audit.py
    tools/
      __init__.py
      football.py
      football_news.py
      knowledge.py
      memory.py
      profile.py
      group.py
      render.py
      image.py
      summary.py
      science.py
      qq_actions.py
      admin.py
```

不要一开始删除原 `arteta_tools.py`。第一阶段让新 agent 包装旧工具，验证稳定后再逐步迁移。

### 2.2 ToolContext

新增 `plugins/arteta_agent/context.py`：

```python
from dataclasses import dataclass, field
from typing import Any, Optional
from nonebot.adapters.onebot.v11 import Bot, MessageEvent

@dataclass
class ToolContext:
    bot: Optional[Bot]
    event: Optional[MessageEvent]
    user_id: str
    group_id: str
    nickname: str = ""
    raw_message: str = ""
    reply_text: str = ""
    image_analysis: str = ""
    is_group: bool = True
    is_admin: bool = False
    request_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
```

作用：

- 工具不再自己到处解析 event。
- 每个工具都可以拿到群号、用户号、昵称、引用消息、图片识别结果。
- 后续 Dashboard 或测试脚本也可以构造 fake context 调工具。

### 2.3 ToolSpec 与注册中心

新增 `plugins/arteta_agent/registry.py`：

```python
from dataclasses import dataclass
from typing import Awaitable, Callable, Any, Literal

PermissionLevel = Literal["safe_read", "safe_write", "confirm_write", "admin_action"]

@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Awaitable[str] | str]
    permission: PermissionLevel = "safe_read"
    enabled: bool = True
    category: str = "general"
    timeout_seconds: float = 20.0

_TOOL_REGISTRY: dict[str, ToolSpec] = {}

def register_tool(spec: ToolSpec):
    if spec.name in _TOOL_REGISTRY:
        raise ValueError(f"Duplicate tool: {spec.name}")
    _TOOL_REGISTRY[spec.name] = spec
    return spec

def get_tool(name: str) -> ToolSpec | None:
    return _TOOL_REGISTRY.get(name)

def list_enabled_tools(include_permissions: set[str] | None = None) -> list[ToolSpec]:
    tools = [t for t in _TOOL_REGISTRY.values() if t.enabled]
    if include_permissions is not None:
        tools = [t for t in tools if t.permission in include_permissions]
    return tools

def build_openai_tools(include_permissions: set[str] | None = None) -> list[dict]:
    result = []
    for spec in list_enabled_tools(include_permissions):
        result.append({
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        })
    return result
```

### 2.4 统一执行器

新增 `plugins/arteta_agent/executor.py`：

```python
import asyncio
import inspect
import json
from .context import ToolContext
from .registry import get_tool
from .permissions import check_permission

async def execute_tool_call(tool_call: dict, ctx: ToolContext) -> str:
    name = tool_call["function"]["name"]
    spec = get_tool(name)
    if not spec:
        return f"[ToolError] 未知工具: {name}"

    try:
        args = json.loads(tool_call["function"].get("arguments") or "{}")
    except json.JSONDecodeError:
        args = {}

    allowed, reason = check_permission(spec, ctx, args)
    if not allowed:
        return f"[PermissionRequired] {reason}"

    async def _run():
        result = spec.handler(ctx=ctx, **args)
        if inspect.isawaitable(result):
            result = await result
        return str(result)

    try:
        return await asyncio.wait_for(_run(), timeout=spec.timeout_seconds)
    except asyncio.TimeoutError:
        return f"[ToolTimeout] {name} 执行超时"
    except Exception as e:
        return f"[ToolError] {name} 执行失败: {type(e).__name__}: {e}"
```

### 2.5 权限控制

新增 `plugins/arteta_agent/permissions.py`：

```python
from .registry import ToolSpec
from .context import ToolContext

def check_permission(spec: ToolSpec, ctx: ToolContext, args: dict) -> tuple[bool, str]:
    if spec.permission == "safe_read":
        return True, ""

    if spec.permission == "safe_write":
        return True, ""

    if spec.permission == "confirm_write":
        if ctx.extra.get("confirmed_tool") == spec.name:
            return True, ""
        return False, f"工具 {spec.name} 会改变状态，需要用户确认。"

    if spec.permission == "admin_action":
        if not ctx.is_admin:
            return False, f"工具 {spec.name} 需要管理员权限。"
        if ctx.extra.get("confirmed_tool") != spec.name:
            return False, f"管理员工具 {spec.name} 需要二次确认。"
        return True, ""

    return False, "未知权限等级。"
```

第一阶段不要实现真正的交互式确认队列，只让工具返回 `[PermissionRequired]`，由 LLM 在最终回复里要求用户确认。第二阶段再做 pending action 表。

### 2.6 Agent Planner / Tool Loop

新增 `plugins/arteta_agent/planner.py`，先复用当前 DeepSeek 调用逻辑，但工具来源改为 Registry：

```python
import httpx
from .registry import build_openai_tools
from .executor import execute_tool_call
from .context import ToolContext

async def call_llm_with_tools(messages, model, api_key, allowed_permissions):
    tools = build_openai_tools(include_permissions=allowed_permissions)
    async with httpx.AsyncClient(timeout=80.0) as client:
        resp = await client.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": "auto",
            },
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
        out = {"role": msg["role"], "content": msg.get("content", "")}
        if msg.get("tool_calls"):
            out["tool_calls"] = msg["tool_calls"]
        if msg.get("reasoning_content"):
            out["reasoning_content"] = msg["reasoning_content"]
        return out

async def run_agent_loop(messages, ctx: ToolContext, model: str, api_key: str, max_rounds: int = 6):
    allowed = {"safe_read", "safe_write", "confirm_write", "admin_action"}
    state = list(messages)

    for _ in range(max_rounds):
        assistant_msg = await call_llm_with_tools(state, model, api_key, allowed)
        state.append(assistant_msg)

        tool_calls = assistant_msg.get("tool_calls") or []
        if not tool_calls:
            content = (assistant_msg.get("content") or "").strip()
            return content or "我需要更多信息才能完成这个任务。"

        for tc in tool_calls:
            result = await execute_tool_call(tc, ctx)
            state.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

    return "我已经尝试了多轮工具调用，但任务还没有稳定完成。请把目标再说具体一点。"
```

## 3. 第一阶段工具迁移清单

### 3.1 football.py

封装现有查询工具：

- get_arsenal_result
- get_pl_table
- get_arsenal_injuries
- search_news

第一阶段可以直接调用旧 `plugins.arteta_tools._get_arsenal_result()` 等函数，降低改动风险。

### 3.2 football_news.py

新增工具：

```text
search_football_news
```

参数：

```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string"},
    "category": {"type": "string", "enum": ["premier_league", "champions_league", "laliga", "serie_a", "bundesliga", "ligue1", "chinese_super_league"]},
    "days": {"type": "integer", "default": 14}
  },
  "required": ["query"]
}
```

注意：当前 `_search_football_news()` 已存在，但没有真正放进主工具列表。优先修复这个断点。

### 3.3 knowledge.py

封装：

- get_football_knowledge
- query_docs_library，可选，后续接 Dashboard Docs Library

### 3.4 memory.py

新增：

- query_group_memory
- add_group_memory
- get_recent_group_context

`query_group_memory` 是 `safe_read`。  
`add_group_memory` 是 `safe_write`，但要限制写入内容长度。

### 3.5 profile.py

新增：

- get_user_profile
- get_current_user_profile
- update_user_profile_by_llm

前两个是 `safe_read`。  
第三个是 `confirm_write` 或后台自动任务，不建议一开始开放给普通 LLM 主动调用。

### 3.6 group.py

新增：

- get_group_members
- get_member_relations
- find_recent_messages_by_alias

这些目前已经有部分函数，封装成工具即可。

### 3.7 render.py

新增：

- render_text_to_tactical_board
- render_markdown_to_image

第一阶段可以不让 LLM 直接发图，只返回 `[RenderedImage: path]` 或 bytes 由上层统一发送。

### 3.8 science.py

封装技术问答能力：

- solve_science_question
- solve_code_question
- solve_math_question

不要让它直接发 QQ 消息，只返回答案文本，由主渲染层统一处理。

目标：用户不用显式输入 `/算法`，普通对话也能让 agent 判断是否调用科学解题工具。

### 3.9 image.py

封装：

- generate_image
- image_to_image，可后续

权限建议：`safe_write`，但要加内容安全与超时处理。

### 3.10 summary.py

封装：

- generate_today_group_summary
- generate_weekly_report
- search_daily_messages

`search_daily_messages` 是 `safe_read`。  
`generate_today_group_summary` 是 `safe_write`。  
自动群发仍保留原定时任务，不建议第一阶段让 LLM 主动群发。

### 3.11 qq_actions.py

后续阶段再做：

- send_like
- mute_member
- send_group_message
- delete_message

权限：

- send_like: confirm_write
- mute_member: admin_action
- send_group_message: confirm_write 或 admin_action
- delete_message: admin_action

### 3.12 admin.py

后续阶段再做：

- run_verify_suite
- read_logs
- check_config
- update_config

权限：

- read_logs: admin_action
- check_config: admin_action
- update_config: admin_action
- run_verify_suite: admin_action

## 4. 与现有 `arteta_chat.py` 的集成方式

### 4.1 不要直接删除 `run_tool_loop`

第一阶段做兼容：

```python
USE_AGENT_REGISTRY = os.environ.get("ARTETA_USE_AGENT_REGISTRY", "false").lower() == "true"
```

在 `process_chat()` 里：

```python
if USE_AGENT_REGISTRY:
    answer = await run_agent_loop(messages, ctx, DEEPSEEK_MODEL, DEEPSEEK_API_KEY)
else:
    answer = await run_tool_loop(messages)
```

这样随时可以通过环境变量回滚。

### 4.2 构造 ToolContext

在 `process_chat()` 已经拿到：

- bot
- event
- user_id
- group_id
- nickname
- raw_message
- quoted_text
- image_analysis
- level/favorability
- 是否管理员

新增：

```python
ctx = ToolContext(
    bot=bot,
    event=event,
    user_id=user_id,
    group_id=group_id,
    nickname=nickname,
    raw_message=raw_message,
    reply_text=quoted_text,
    image_analysis=image_analysis,
    is_group=isinstance(event, GroupMessageEvent),
    is_admin=str(user_id) == ADMIN_QQ,
    request_id=f"{group_id}_{user_id}_{int(time.time()*1000)}",
)
```

### 4.3 Prompt 调整

当前 ARTETA_PROMPT 里只提示了 `get_football_knowledge`、`get_group_members`、`get_member_relations`。

新增 agent 工具原则：

```text
【工具使用原则】：
- 你可以使用工具完成查询、记忆、画像、总结、图片分析、科学解题等任务。
- 需要事实数据时，优先调用工具，不要凭印象编造。
- 用户请求涉及今天、最近、最新、新闻、赛程、比分、伤病、转会时，必须调用对应查询工具。
- 用户询问群成员、谁说过什么、某人档案、群内关系时，调用群成员/画像/记忆工具。
- 用户的问题明显是数学、物理、算法、代码题时，调用科学解题工具。
- 工具返回 PermissionRequired 时，不要假装已执行，应向用户说明需要确认或管理员权限。
```

## 5. 验收标准

### 5.1 基础验收

1. 原有命令仍然可用：
   - A/塔子 对话
   - 算法
   - 档案
   - 好感度
   - 好感度排行
   - 清除记忆
2. `ARTETA_USE_AGENT_REGISTRY=false` 时行为与旧版一致。
3. `ARTETA_USE_AGENT_REGISTRY=true` 时主聊天走新 Registry。
4. 原 7 个工具全部可通过新 Registry 调用。
5. 工具不存在时返回可读错误，不崩溃。
6. 工具超时时返回可读错误，不阻塞整个 bot。

### 5.2 自主性验收用例

自然语言：

```text
塔子，最近阿森纳有什么新闻？
```

期望：调用 `search_football_news` 或 `search_news`。

```text
塔子，看看我档案里你记得我什么？
```

期望：调用 `get_current_user_profile`。

```text
塔子，刚才群里他们在吵什么？
```

期望：调用 `get_recent_group_context` 或 `search_daily_messages`。

```text
塔子，这张物理题怎么做？
```

期望：如果有图片识别结果，调用 `solve_science_question`。

```text
塔子，给我点个赞。
```

期望：返回需要确认或调用 `send_like` 的 confirm_write 流程，不应无权限乱执行。

```text
塔子，把某人禁言。
```

期望：非管理员返回权限不足；管理员也需要二次确认。

### 5.3 验证脚本

扩展 `tools/verify_features.py`：

新增 suite：

```text
agent_registry
agent_permissions
agent_loop
```

测试项：

- 工具注册数量 > 0。
- 重复工具名会报错。
- safe_read 工具可执行。
- confirm_write 未确认时返回 PermissionRequired。
- admin_action 非管理员时拒绝。
- 构造 fake ToolContext 可以调用 profile/memory 查询。
- run_agent_loop 能处理未知工具、工具异常、工具超时。

## 6. 分阶段实施计划

### Phase 1：加统一工具层，但不改业务逻辑

目标：

- 新增 `plugins/arteta_agent/` 包。
- 实现 ToolContext、ToolSpec、Registry、Executor、Permissions。
- 包装原 `arteta_tools.py` 的 7 个工具。
- 加环境变量开关。

不做：

- 不迁移画图、日报、禁言。
- 不删除旧工具。
- 不改数据库结构。

验收：

```bash
python tools/verify_features.py --suite core
python tools/verify_features.py --suite chat
python tools/verify_features.py --suite agent_registry
```

### Phase 2：扩充 read-only 工具

新增：

- search_football_news
- get_user_profile
- query_group_memory
- get_recent_group_context
- find_recent_messages_by_alias

目标：

- 普通对话能自主查档案、查记忆、查群聊上下文、查足球新闻向量库。

验收：

- “最近阿森纳新闻” 能触发足球新闻工具。
- “我档案里写了什么” 能触发 profile 工具。
- “某某刚才说了什么” 能触发 recent messages / alias 工具。

### Phase 3：接入低风险生成工具

新增：

- solve_science_question
- generate_today_group_summary
- render_markdown_to_image
- generate_image

目标：

- 普通对话可以自主判断数学/物理/代码题。
- 可以把“今天群聊总结一下”变成自然语言功能。
- 可以让主 agent 调用图片生成，但最终发送仍由上层控制。

验收：

- 不输入 `/算法` 也能识别理科题。
- 不输入 `/日报` 也能生成当前群摘要。
- 图片生成失败不影响主进程。

### Phase 4：接入需确认工具

新增：

- send_like
- clear_memory
- update_user_profile_by_llm

目标：

- 工具权限层生效。
- 用户确认后才执行状态变更。

需要新增 pending action 表或内存缓存：

```sql
CREATE TABLE IF NOT EXISTS pending_agent_actions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
```

### Phase 5：接入管理员工具

新增：

- mute_member
- read_logs
- run_verify_suite
- check_config
- update_config

目标：

- 只允许管理员自然语言触发。
- 必须二次确认。
- 所有操作写 audit log。

## 7. 风险与注意事项

### 7.1 密钥处理

当前源码中存在硬编码密钥痕迹，应立即：

1. 移除源码硬编码默认 key。
2. 改为 `.env` / Dashboard 配置。
3. 已上传或共享过的 key 直接轮换。
4. 在 `.gitignore` 确保 `.env`、日志、数据库、ChromaDB 目录不提交。

### 7.2 不要让 LLM 直接控制 QQ 副作用

所有 QQ 副作用类工具必须经过权限层：

- 发消息
- 点赞
- 禁言
- 删除
- 清空记忆
- 修改配置

### 7.3 保留旧命令作为 fallback

用户已经习惯命令，不要一次性改掉。重构目标是增强自然语言入口，不是删除命令。

### 7.4 避免 prompt 继续膨胀

把能查的内容交给工具，不要全部预注入 prompt。长期方向：

- 只注入最必要上下文。
- 详细数据由工具按需检索。
- 对用户画像做摘要，而不是全量塞入。

## 8. 最终目标架构

```text
用户消息
  │
  ▼
NoneBot 入口层
  │
  ├─ 兼容旧命令
  │
  └─ 自然语言 / @机器人 / A前缀
        │
        ▼
  Context Builder
        │
        ├─ 解析用户、群、引用、图片、权限
        └─ 构造 ToolContext
        │
        ▼
  Agent Planner
        │
        ├─ LLM + Tool Registry
        ├─ tool_calls
        ├─ Permission Check
        ├─ Tool Execution
        └─ Observation Loop
        │
        ▼
  Response Postprocess
        │
        ├─ 好感度标记
        ├─ 记忆写入
        ├─ 画像异步更新
        └─ 渲染图片
        │
        ▼
  QQ 输出
```