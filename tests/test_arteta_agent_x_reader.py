def test_x_reader_formats_bridge_and_generated_provenance():
    from plugins.arteta_agent.tools.web.x_reader import (
        X_PROVENANCE_CONFIGURED_BRIDGE,
        X_PROVENANCE_GENERATED_EXTRACTION,
        _format_x_post,
    )

    bridge_text = _format_x_post(
        {
            "url": "https://x.com/David_Ornstein/status/2074251813545742720",
            "author_name": "David Ornstein",
            "author_username": "David_Ornstein",
            "text": "Arsenal update from bridge.",
            "backend": "ignored",
        },
        "https://x.com/David_Ornstein/status/2074251813545742720",
        provenance=X_PROVENANCE_CONFIGURED_BRIDGE,
        backend="playwright-profile",
    )

    generated_text = _format_x_post(
        {
            "url": "https://x.com/David_Ornstein/status/2074251813545742720",
            "author_name": "",
            "author_username": "",
            "text": "Generated extraction text.",
        },
        "https://x.com/David_Ornstein/status/2074251813545742720",
        provenance=X_PROVENANCE_GENERATED_EXTRACTION,
    )

    assert "provenance: configured_bridge" in bridge_text
    assert "bridge_backend: playwright-profile" in bridge_text
    assert "David Ornstein (@David_Ornstein)" in bridge_text
    assert "provenance: generated_extraction" in generated_text
    assert "作者：" not in generated_text


def test_x_reader_rejects_mirror_metadata_for_different_author():
    from plugins.arteta_agent.tools.web.x_reader import _format_x_mirror_page, _x_status_id, _x_username

    source_url = "https://x.com/David_Ornstein/status/2074251813545742720"
    mirror_page = {
        "title": "Wrong Person (@wrong) on X",
        "description": "This should not be accepted for the requested author.",
        "url": "https://vxtwitter.com/wrong/status/2074251813545742720",
    }

    assert _x_status_id(source_url) == "2074251813545742720"
    assert _x_username(source_url) == "david_ornstein"
    assert _format_x_mirror_page(mirror_page, source_url) == ""
