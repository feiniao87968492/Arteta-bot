import json

from plugins.arteta_football_intelligence.entities import extract_entities, load_entity_catalog


def test_default_entity_catalog_handles_chinese_and_english_aliases():
    catalog = load_entity_catalog("")

    result = extract_entities("萨卡在阿森纳的英超比赛前恢复训练", catalog)

    assert result.teams == ["Arsenal"]
    assert result.players == ["Bukayo Saka"]
    assert result.competitions == ["Premier League"]


def test_entity_catalog_loads_watchlist_aliases(tmp_path):
    path = tmp_path / "entities.json"
    path.write_text(json.dumps({
        "teams": {"Roma": ["罗马", "AS Roma"]},
        "players": {"Victor Osimhen": ["奥斯梅恩", "Osimhen"]},
        "competitions": {},
    }), encoding="utf-8")

    catalog = load_entity_catalog(str(path))
    result = extract_entities("罗马正在关注奥斯梅恩", catalog)

    assert result.teams == ["Roma"]
    assert result.players == ["Victor Osimhen"]
