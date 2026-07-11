from dashboard.api.services.verify_service import VerifyService


def test_build_args_for_suite_and_case(tmp_path):
    service = VerifyService(str(tmp_path))
    args = service.build_args(["core", "render"], ["html_to_image"], online=False, allow_side_effects=False)
    assert args.count("--suite") == 2
    assert "core" in args
    assert "render" in args
    assert "--case" in args
    assert "html_to_image" in args
    assert "--online" not in args


def test_build_args_accepts_agent_registry_suite(tmp_path):
    service = VerifyService(str(tmp_path))
    args = service.build_args(["agent_registry"], ["phase5_admin_tools"], online=False, allow_side_effects=False)
    assert args == ["--suite", "agent_registry", "--case", "phase5_admin_tools"]


def test_build_args_accepts_agent_permissions_and_loop_suites(tmp_path):
    service = VerifyService(str(tmp_path))
    args = service.build_args(["agent_permissions", "agent_loop"], [], online=False, allow_side_effects=False)
    assert args == ["--suite", "agent_permissions", "--suite", "agent_loop"]


def test_build_args_rejects_unknown_suite(tmp_path):
    service = VerifyService(str(tmp_path))
    try:
        service.build_args(["bad"], [], online=False, allow_side_effects=False)
    except ValueError as exc:
        assert "suite" in str(exc)
    else:
        raise AssertionError("unknown suite accepted")
