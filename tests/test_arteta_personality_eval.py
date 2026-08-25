from pathlib import Path


def test_personality_eval_fixture_schema_and_coverage():
    from tools.evaluate_personality_style import load_records, validate_records

    dataset = Path("tests/fixtures/personality_eval_cases.json")
    records = load_records(str(dataset))
    summary = validate_records(records)

    assert summary["total"] >= 40
    assert summary["mode_counts"]["casual"] >= 3
    assert summary["mode_counts"]["meme"] >= 3
    assert summary["mode_counts"]["football_opinion"] >= 3
    assert summary["mode_counts"]["current_news"] >= 3
    assert summary["mode_counts"]["tactical_deep_dive"] >= 3
    assert summary["mode_counts"]["serious"] >= 3
    assert summary["explicit_emoji_cases"] >= 1
    assert summary["trace_query_cases"] >= 1
    assert summary["image_cases"] >= 2
    assert summary["screenshot_regression_cases"] >= 2


def test_personality_eval_report_records_current_baseline_flags():
    from tools.evaluate_personality_style import evaluate_records, load_records

    records = load_records("tests/fixtures/personality_eval_cases.json")
    report = evaluate_records(records)

    assert report["total"] >= 40
    assert "mode_counts" in report
    assert "expected_ratios" in report
    assert "current_code_baseline" in report
    assert "risk_flags" in report
    assert report["current_code_baseline"]["mood_forces_positive_neutral"] is False
    assert report["current_code_baseline"]["trace_prefixes_grok_marker"] is False
    assert report["risk_flags"]["forced_neutral_emoji_cases"] == 0
    assert report["risk_flags"]["visible_trace_marker_cases"] == 0


def test_personality_eval_baseline_checks_favorability_marker_only_in_default_prompt():
    from tools.evaluate_personality_style import evaluate_records, load_records

    records = load_records("tests/fixtures/personality_eval_cases.json")
    report = evaluate_records(records)

    assert report["current_code_baseline"]["favorability_prompt_marker_required"] is False
    assert report["risk_flags"]["visible_favorability_cases"] == 0
