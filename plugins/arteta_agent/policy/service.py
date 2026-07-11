from .. import behavior_policy


def has_expiring_behavior_policies(group_id: str) -> bool:
    return any(
        "ttl_turns" in item
        for item in behavior_policy.list_group_policies(group_id).values()
    )


def should_consume_policy_turn(group_id: str, disabled_tools) -> bool:
    return bool(disabled_tools) or has_expiring_behavior_policies(group_id)


def consume_policy_turn_if_needed(group_id: str, should_consume: bool) -> None:
    if should_consume:
        behavior_policy.consume_group_policy_turn(group_id)


def mood_emoji_enabled(group_id: str) -> bool:
    policy = behavior_policy.get_group_policy(group_id, "emoji.enabled")
    if not policy:
        return True
    return policy.get("value") is not False
