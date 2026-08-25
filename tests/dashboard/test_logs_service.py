from dashboard.api.services.logs_service import LogsService



def test_list_logs_includes_only_allowed_log_names(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "arteta_bot.log").write_text("line\n", encoding="utf-8")
    (logs / "dashboard_audit.log").write_text("audit\n", encoding="utf-8")
    (logs / "other.log").write_text("skip\n", encoding="utf-8")
    service = LogsService(str(logs))

    result = service.list_logs()

    names = [item["name"] for item in result]
    assert names == ["arteta_bot.log", "dashboard_audit.log"]
    assert result[0]["size"] > 0
    assert result[0]["mtime"] > 0



def test_tail_returns_last_lines(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "arteta_bot.log").write_text("one\ntwo\nthree\n", encoding="utf-8")
    service = LogsService(str(logs))

    assert service.tail("arteta_bot.log", limit=2) == ["two", "three"]



def test_path_traversal_rejected(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    service = LogsService(str(logs))

    try:
        service.tail("../secret.log")
    except ValueError as exc:
        assert "not allowed" in str(exc)
    else:
        raise AssertionError("path traversal was not rejected")
