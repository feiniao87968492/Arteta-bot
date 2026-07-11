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
