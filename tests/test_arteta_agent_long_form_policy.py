from plugins.arteta_agent.response.length_policy import (
    LongFormResponsePolicy,
    build_dynamic_response_constraints,
    resolve_long_form_policy,
)


def test_short_input_defaults_to_expanded_policy():
    policy = resolve_long_form_policy("早")

    assert isinstance(policy, LongFormResponsePolicy)
    assert policy.mode == "expanded"
    assert policy.target_min_chars >= 250
    assert "short_input_long_answer" in policy.reason_codes


def test_explicit_concise_request_overrides_long_form():
    policy = resolve_long_form_policy("只告诉我答案，x1+2x2=3 有几个正整数解？")

    assert policy.mode == "concise"
    assert policy.target_max_chars <= 250
    assert "explicit_concise_request" in policy.reason_codes


def test_math_and_tactics_promote_to_deep_policy():
    math_policy = resolve_long_form_policy("x1+2x2+3x3+4x4=13 的正整数解有多少？")
    tactics_policy = resolve_long_form_policy("详细讲讲阿森纳右路进攻结构")

    assert math_policy.mode == "deep"
    assert "technical_or_math" in math_policy.reason_codes
    assert tactics_policy.mode == "deep"
    assert "explicit_deep_request" in tactics_policy.reason_codes


def test_policy_constraints_describe_expanded_structure_without_fixed_actions():
    policy = resolve_long_form_policy("罗杰斯适合阿森纳吗")

    text = build_dynamic_response_constraints(policy)

    assert "【本轮回答模式：expanded】" in text
    assert "第一部分直接回答" in text
    assert "3～6 个自然段" in text
    assert "拍桌子" not in text
    assert "敲战术板" not in text


def test_permission_and_tool_failures_are_controlled_concise():
    permission_policy = resolve_long_form_policy("确认执行 mute_member", stop_reason="waiting_confirmation")
    failure_policy = resolve_long_form_policy("萨卡伤了吗", tool_failure=True)

    assert permission_policy.mode == "concise"
    assert "permission_or_confirmation" in permission_policy.reason_codes
    assert failure_policy.mode == "concise"
    assert "tool_failure" in failure_policy.reason_codes
