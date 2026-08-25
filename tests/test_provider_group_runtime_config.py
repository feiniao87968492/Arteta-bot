from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_chat_runtime_does_not_embed_a_football_data_token():
    source = (ROOT / "plugins" / "arteta_chat.py").read_text(encoding="utf-8")

    assert 'config.get("football_api_token", "")' in source
    assert "da24063a4040404c89250b601f8994a2" not in source
