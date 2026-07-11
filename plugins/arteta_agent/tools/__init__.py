def register_phase1_tools():
    # Phase 1 keeps the original football/read tools behind the registry.
    from . import football

    football.register_tools()


def register_phase2_tools():
    # Phase 2 adds group/profile/memory read tools. These must remain scoped by
    # ToolContext group_id/user_id inside each tool implementation.
    from . import document, football_news, group, link_analysis, memory, profile, summary, web_access

    football_news.register_tools()
    profile.register_tools()
    memory.register_tools()
    group.register_tools()
    summary.register_read_tools()
    web_access.register_tools()
    document.register_tools()
    link_analysis.register_tools()


def register_phase3_tools():
    # Phase 3 tools generate content or images but should not directly mutate
    # QQ/group state.
    from . import behavior_policy, image, render, science, summary, trace, ui_preferences

    science.register_tools()
    summary.register_tools()
    render.register_tools()
    image.register_tools()
    trace.register_tools()
    behavior_policy.register_tools()
    ui_preferences.register_tools()


def register_phase4_tools():
    # Phase 4 tools may change state, so executor.py must gate them through the
    # confirm_write pending-action path.
    from . import memory_actions, profile_actions, qq_actions

    qq_actions.register_tools()
    memory_actions.register_tools()
    profile_actions.register_tools()


def register_phase5_tools():
    # Phase 5 tools are admin-only and require admin_action permission checks.
    from . import admin

    admin.register_tools()


def register_all_tools():
    register_phase1_tools()
    register_phase2_tools()
    register_phase3_tools()
    register_phase4_tools()
    register_phase5_tools()
