SCENARIOS = [
    "One-word greeting",
    "Short football opinion",
    "Image or meme explanation",
    "Latest injury",
    "Transfer news",
    "Math short question",
    "Algorithm question",
    "Document summary",
    "Group memory",
    "Explicit concise request",
    "Tool timeout fallback",
    "Admin confirmation tool",
]


def _write_complete_evidence(tmp_path, mutate_sample=None):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    for index in range(1, 13):
        (evidence_dir / ("sample-%02d.png" % index)).write_bytes(b"png")
    for name in [
        "news-before.png",
        "news-after.png",
        "math-before.png",
        "math-after.png",
        "meme-before.png",
        "meme-after.png",
        "short-before.png",
        "short-after.png",
        "concise-before.png",
        "concise-after.png",
    ]:
        (evidence_dir / name).write_bytes(b"png")

    no_tool_scenarios = set([
        "One-word greeting",
        "Short football opinion",
        "Explicit concise request",
    ])
    sample_rows = []
    for index, scenario in enumerate(SCENARIOS, 1):
        row = {
            "#": str(index),
            "Scenario": scenario,
            "User input summary": "operator sample %d" % index,
            "Screenshot path or reference": "evidence/sample-%02d.png" % index,
            "Progress sequence": "[Agent] received > [Action] checked > [Observation] summarized",
            "Real tool order": "n/a" if scenario in no_tool_scenarios else "tool_%02d" % index,
            "Final answer structure and length": "structured final reply with enough detail",
            "Transport": "text" if index != 3 else "image",
            "Reporter closed before final reply": "yes",
            "Internal parameter leak": "no",
            "Pass/Fail": "Pass",
            "Notes": "redacted live QQ evidence",
        }
        if mutate_sample:
            mutate_sample(index, scenario, row)
        sample_rows.append(
            "| {#} | {Scenario} | {User input summary} | {Screenshot path or reference} | {Progress sequence} | {Real tool order} | {Final answer structure and length} | {Transport} | {Reporter closed before final reply} | {Internal parameter leak} | {Pass/Fail} | {Notes} |".format(**row)
        )

    markdown = """
# Agent Progress Long-Form Manual Evidence

| # | Scenario | User input summary | Screenshot path or reference | Progress sequence | Real tool order | Final answer structure and length | Transport | Reporter closed before final reply | Internal parameter leak | Pass/Fail | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
{sample_rows}

| Item | Before screenshot | After screenshot | What changed | Pass/Fail | Notes |
| --- | --- | --- | --- | --- | --- |
| Progress during long-running current-news reply | evidence/news-before.png | evidence/news-after.png | progress is visible before final reply | Pass | checked |
| Progress during math tool reply | evidence/math-before.png | evidence/math-after.png | progress is visible before final reply | Pass | checked |
| Progress during image/meme explanation | evidence/meme-before.png | evidence/meme-after.png | progress is visible before final reply | Pass | checked |
| Short input default expanded reply | evidence/short-before.png | evidence/short-after.png | final reply is expanded | Pass | checked |
| Explicit concise request remains concise | evidence/concise-before.png | evidence/concise-after.png | final reply stays concise | Pass | checked |
""".format(sample_rows="\n".join(sample_rows))
    evidence_file = tmp_path / "agent-progress.md"
    evidence_file.write_text(markdown, encoding="utf-8")
    return evidence_file


def test_agent_progress_manual_evidence_template_is_not_complete_acceptance():
    from tools.validate_agent_progress_longform_manual_evidence import validate_manual_evidence

    result = validate_manual_evidence(
        "Docs/dev/agent-progress-longform-manual-evidence.md",
        repo_root=".",
    )

    assert result["ok"] is False
    assert result["sample_rows"] == 12
    assert result["before_after_rows"] == 5
    assert any("missing" in error.lower() for error in result["errors"])


def test_agent_progress_manual_evidence_accepts_complete_redacted_evidence(tmp_path):
    from tools.validate_agent_progress_longform_manual_evidence import validate_manual_evidence

    evidence_file = _write_complete_evidence(tmp_path)

    result = validate_manual_evidence(str(evidence_file), repo_root=str(tmp_path))

    assert result["ok"] is True
    assert result["sample_rows"] == 12
    assert result["before_after_rows"] == 5
    assert result["scenario_counts"] == {scenario: 1 for scenario in SCENARIOS}
    assert result["errors"] == []


def test_agent_progress_manual_evidence_rejects_trace_leaks_and_missing_tool_order(tmp_path):
    from tools.validate_agent_progress_longform_manual_evidence import validate_manual_evidence

    def mutate(index, scenario, row):
        if scenario == "Latest injury":
            row["Progress sequence"] = "[Thought] hidden reasoning > [Action] get_arsenal_injuries"
            row["Real tool order"] = "n/a"
            row["Internal parameter leak"] = "yes"

    evidence_file = _write_complete_evidence(tmp_path, mutate_sample=mutate)

    result = validate_manual_evidence(str(evidence_file), repo_root=str(tmp_path))

    assert result["ok"] is False
    joined_errors = "\n".join(result["errors"]).lower()
    assert "[thought]" in joined_errors
    assert "real tool order" in joined_errors
    assert "internal parameter leak" in joined_errors
