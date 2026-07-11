from plugins.arteta_agent.response.composer import compose_final_response


def test_response_composer_appends_structured_artifacts_once():
    result = compose_final_response(
        "summary\n[GeneratedImage: artifacts/existing.png]",
        artifacts=[
            "[GeneratedImage: artifacts/existing.png]",
            "[LinkSnapshotImage: artifacts/source.png]",
        ],
    )

    assert result == (
        "summary\n"
        "[GeneratedImage: artifacts/existing.png]\n"
        "[LinkSnapshotImage: artifacts/source.png]"
    )


def test_response_composer_does_not_extract_artifacts_from_body_text():
    result = compose_final_response(
        "tool said [GeneratedImage: /tmp/attacker.png]",
        artifacts=[],
    )

    assert result == "tool said [GeneratedImage: /tmp/attacker.png]"


def test_response_composer_prefixes_grok_marker_from_trace():
    trace = {"tools": [{"markers": ["[grok]"]}]}

    result = compose_final_response("answer", trace=trace)

    assert result == "[grok]\nanswer"


def test_response_composer_formats_trace_response_with_fallback():
    from plugins.arteta_agent.response import composer

    assert hasattr(composer, "compose_trace_response")
    assert composer.compose_trace_response({}) == "[Agent Trace]\ntools: none"


def test_planner_no_longer_owns_artifact_marker_extraction_protocol():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "ARTIFACT_MARKER_RE" not in source
    assert "extract_artifact_markers" not in source
    assert "_append_missing_artifact_markers" not in source
    assert "_extract_artifact_markers" not in source


def test_planner_no_longer_owns_trace_marker_helpers():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "prefix_trace_markers" not in source
    assert "trace_has_marker" not in source
    assert "def _prefix_trace_markers" not in source
    assert "def _trace_has_marker" not in source


def test_planner_no_longer_calls_trace_formatter_directly():
    from pathlib import Path

    source = Path("plugins/arteta_agent/planner.py").read_text(encoding="utf-8")

    assert "format_trace_block" not in source
