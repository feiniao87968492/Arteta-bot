from pathlib import Path


def test_manual_evidence_template_is_not_complete_acceptance():
    from tools.validate_personality_manual_evidence import validate_manual_evidence

    result = validate_manual_evidence(
        "Docs/dev/personality-response-manual-evidence.md",
        repo_root=".",
    )

    assert result["ok"] is False
    assert result["sample_rows"] == 12
    assert result["before_after_rows"] == 5
    assert any("missing" in error.lower() for error in result["errors"])


def test_manual_evidence_validator_accepts_complete_redacted_evidence(tmp_path):
    from tools.validate_personality_manual_evidence import validate_manual_evidence

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    for index in range(1, 13):
        (evidence_dir / ("sample-%02d.png" % index)).write_bytes(b"png")
    for name in [
        "short-before.png",
        "short-after.png",
        "meme-before.png",
        "meme-after.png",
        "tactical-before.png",
        "tactical-after.png",
        "news-before.png",
        "news-after.png",
        "trace-before.png",
        "trace-after.png",
    ]:
        (evidence_dir / name).write_bytes(b"png")

    sample_categories = [
        "daily chat",
        "daily chat",
        "daily chat",
        "meme/image",
        "meme/image",
        "football opinion",
        "football opinion",
        "latest news",
        "latest news",
        "tactical deep dive",
        "tactical deep dive",
        "Trace query",
    ]
    sample_rows = []
    for index, category in enumerate(sample_categories, 1):
        trace_visible = "yes" if category == "Trace query" else "no"
        source_display = "yes" if category == "latest news" else "n/a"
        sample_rows.append(
            "| {index} | {category} | input {index} | evidence/sample-{index:02d}.png | First sentence {index}. | 42 | 2 | no | text | {trace} | no | {source} | Pass | checked |".format(
                index=index,
                category=category,
                trace=trace_visible,
                source=source_display,
            )
        )

    markdown = """
# Personality Response Manual Evidence Checklist

| # | Category | User input summary | Screenshot path or reference | First sentence | Character count | Paragraph count | Emoji sent | Transport | Trace visible | Favorability visible | Source display | Pass/Fail | Notes |
| --- | --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- |
{sample_rows}

| Item | Before screenshot | After screenshot | What changed | Pass/Fail | Notes |
| --- | --- | --- | --- | --- | --- |
| Short plain reply | evidence/short-before.png | evidence/short-after.png | text transport | Pass | checked |
| Meme/image reply | evidence/meme-before.png | evidence/meme-after.png | shorter reply | Pass | checked |
| Long tactical reply | evidence/tactical-before.png | evidence/tactical-after.png | cleaner card | Pass | checked |
| Current news reply | evidence/news-before.png | evidence/news-after.png | natural sources | Pass | checked |
| Explicit Trace query | evidence/trace-before.png | evidence/trace-after.png | sanitized trace | Pass | checked |
""".format(sample_rows="\n".join(sample_rows))
    evidence_file = tmp_path / "manual.md"
    evidence_file.write_text(markdown, encoding="utf-8")

    result = validate_manual_evidence(str(evidence_file), repo_root=str(tmp_path))

    assert result["ok"] is True
    assert result["sample_rows"] == 12
    assert result["before_after_rows"] == 5
    assert result["errors"] == []
