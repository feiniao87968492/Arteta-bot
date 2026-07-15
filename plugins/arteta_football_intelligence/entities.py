import json
from dataclasses import dataclass, field
from typing import Dict, List


DEFAULT_ENTITY_CONFIG = {
    "teams": {
        "Arsenal": ["阿森纳", "Arsenal", "Gunners"],
        "Chelsea": ["切尔西", "Chelsea"],
        "Manchester City": ["曼城", "Manchester City", "Man City"],
    },
    "players": {
        "Bukayo Saka": ["萨卡", "Bukayo Saka", "Saka"],
        "Declan Rice": ["赖斯", "Declan Rice", "Rice"],
        "Martin Odegaard": ["厄德高", "Odegaard", "Martin Odegaard"],
    },
    "competitions": {
        "Premier League": ["英超", "Premier League", "EPL"],
        "Champions League": ["欧冠", "Champions League", "UCL"],
    },
}


@dataclass
class EntityCatalog:
    teams: Dict[str, List[str]] = field(default_factory=dict)
    players: Dict[str, List[str]] = field(default_factory=dict)
    competitions: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class EntityExtraction:
    teams: List[str] = field(default_factory=list)
    players: List[str] = field(default_factory=list)
    competitions: List[str] = field(default_factory=list)


def load_entity_catalog(path: str) -> EntityCatalog:
    raw = DEFAULT_ENTITY_CONFIG
    if path:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                raw = loaded
        except Exception:
            raw = DEFAULT_ENTITY_CONFIG
    return EntityCatalog(
        teams=_coerce_alias_mapping(raw.get("teams") or {}),
        players=_coerce_alias_mapping(raw.get("players") or {}),
        competitions=_coerce_alias_mapping(raw.get("competitions") or {}),
    )


def extract_entities(text: str, catalog: EntityCatalog) -> EntityExtraction:
    return EntityExtraction(
        teams=_extract_alias_hits(text, catalog.teams),
        players=_extract_alias_hits(text, catalog.players),
        competitions=_extract_alias_hits(text, catalog.competitions),
    )


def _coerce_alias_mapping(value) -> Dict[str, List[str]]:
    result = {}
    for canonical, aliases in dict(value or {}).items():
        result[str(canonical)] = [str(alias) for alias in list(aliases or []) if str(alias).strip()]
    return result


def _extract_alias_hits(text: str, mapping: Dict[str, List[str]]) -> List[str]:
    haystack = str(text or "").lower()
    hits = []
    for canonical, aliases in mapping.items():
        for alias in aliases + [canonical]:
            if str(alias).lower() in haystack:
                hits.append(canonical)
                break
    return hits
