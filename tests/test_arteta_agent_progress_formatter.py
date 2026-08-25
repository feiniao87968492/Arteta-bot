from plugins.arteta_agent.progress.formatter import (
    ProgressFormatterPolicy,
    format_progress_event,
)
from plugins.arteta_agent.progress.models import (
    PROGRESS_FINAL_SYNTHESIS_HEARTBEAT,
    PROGRESS_FINAL_SYNTHESIS_STARTED,
    PROGRESS_TOOL_BATCH_FINISHED,
    PROGRESS_TOOL_BATCH_STARTED,
    PROGRESS_WAITING_CONFIRMATION,
    AgentProgressEvent,
    ProgressToolCall,
)


def test_formatter_shows_real_grok_search_tool_name_without_parameters():
    message = format_progress_event(AgentProgressEvent(
        kind=PROGRESS_TOOL_BATCH_STARTED,
        tools=[ProgressToolCall(
            call_id="call-1",
            name="grok_search",
            permission="safe_read",
            argument_keys=["query"],
        )],
    ))

    assert message == "[Action] 我将调用 grok_search 实时检索服务，检索最新新闻、官宣、记者原帖和 X/Twitter 实时线索。"
    assert "query" not in message
    assert "[Thought]" not in message
    assert "🔎" not in message


def test_formatter_uses_math_specific_action_copy():
    message = format_progress_event(AgentProgressEvent(
        kind=PROGRESS_TOOL_BATCH_STARTED,
        tools=[ProgressToolCall(
            call_id="call-math",
            name="solve_math_question",
            permission="safe_read",
        )],
    ))

    assert message == "[Action] 我将调用 solve_math_question 数学专用解题 Agent 服务，核对题目条件并完成推导。"


def test_formatter_observation_uses_safe_duration_and_error_whitelist():
    timeout = format_progress_event(AgentProgressEvent(
        kind=PROGRESS_TOOL_BATCH_FINISHED,
        tools=[ProgressToolCall(call_id="call-1", name="web_fetch")],
        status="timeout",
        duration_ms=2100,
        error_code="TimeoutError",
    ))
    unsafe = format_progress_event(AgentProgressEvent(
        kind=PROGRESS_TOOL_BATCH_FINISHED,
        tools=[ProgressToolCall(call_id="call-2", name="web_fetch")],
        status="error",
        duration_ms=5,
        error_code="ValueError: https://secret.example/?token=abc",
    ))

    assert timeout == "[Observation] web_fetch 调用超时（2.1 秒），未获得可用结果。"
    assert unsafe == "[Observation] web_fetch 调用失败（ToolError），未获得可用结果。"
    assert "secret" not in unsafe
    assert "token" not in unsafe


def test_formatter_suppresses_silent_tools_and_handles_confirmation():
    silent = format_progress_event(AgentProgressEvent(
        kind=PROGRESS_TOOL_BATCH_STARTED,
        tools=[ProgressToolCall(call_id="emoji", name="send_mood_emoji", permission="safe_write")],
    ))
    confirmation = format_progress_event(AgentProgressEvent(
        kind=PROGRESS_WAITING_CONFIRMATION,
        tools=[ProgressToolCall(call_id="mute", name="mute_member", permission="admin_action")],
    ))

    assert silent == ""
    assert confirmation == "[Confirmation] mute_member 需要管理员权限和二次确认，当前尚未执行。"
    assert "已执行" not in confirmation


def test_formatter_merges_parallel_safe_tools():
    message = format_progress_event(AgentProgressEvent(
        kind=PROGRESS_TOOL_BATCH_STARTED,
        tools=[
            ProgressToolCall(call_id="a", name="get_arsenal_result"),
            ProgressToolCall(call_id="b", name="get_pl_table"),
            ProgressToolCall(call_id="c", name="get_arsenal_injuries"),
        ],
    ))

    assert message == "[Action] 我将并行调用 get_arsenal_result、get_pl_table 和 get_arsenal_injuries 服务，核对赛果、积分榜和伤病信息。"


def test_formatter_final_synthesis_messages_are_scene_aware():
    math_message = format_progress_event(AgentProgressEvent(
        kind=PROGRESS_FINAL_SYNTHESIS_STARTED,
        metadata={"scene": "math"},
    ))
    image_message = format_progress_event(AgentProgressEvent(
        kind=PROGRESS_FINAL_SYNTHESIS_STARTED,
        metadata={"scene": "image"},
    ))
    heartbeat = format_progress_event(AgentProgressEvent(kind=PROGRESS_FINAL_SYNTHESIS_HEARTBEAT))

    assert math_message == "[Agent] 解题结果已经返回，我将补全方法、关键步骤、验证和最终答案。"
    assert image_message == "[Agent] 图片内容已经识别完成，我将从画面信息、背景和核心含义三个层面展开说明。"
    assert heartbeat == "[Agent] 详细回答仍在生成，我正在整理结构、论据和排版。"


def test_formatter_policy_can_hide_observations():
    message = format_progress_event(
        AgentProgressEvent(
            kind=PROGRESS_TOOL_BATCH_FINISHED,
            tools=[ProgressToolCall(call_id="call", name="grok_search")],
            status="ok",
            duration_ms=1100,
        ),
        ProgressFormatterPolicy(show_observations=False),
    )

    assert message == ""
