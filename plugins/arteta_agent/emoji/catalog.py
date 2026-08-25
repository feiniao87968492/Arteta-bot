import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import EmojiAsset


LOGGER = logging.getLogger(__name__)

EMOJI_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_MANIFEST_BYTES = 256 * 1024


LEGACY_REACTION_HINTS = (
    ("celebration", ("开心", "高兴", "庆祝", "happy", "celebration")),
    ("approval", ("赞同", "满意", "approval", "agree")),
    ("thinking", ("思考", "想想", "分析", "thinking", "think")),
    ("speechless", ("无聊", "冷场", "平淡", "无语", "speechless", "bored")),
    ("surprised", ("震惊", "惊讶", "surprised", "shock")),
    ("skeptical", ("疑惑", "怀疑", "质疑", "靠不靠谱", "skeptical", "doubt", "stare")),
    ("frustrated", ("生气", "愤怒", "不满", "红温", "angry", "frustrated")),
    ("sad", ("哭", "哭泣", "难过", "委屈", "遗憾", "sad")),
)


def _resolve_root(base_dir: str) -> Optional[Path]:
    if not base_dir:
        return None
    root = Path(base_dir)
    if not root.exists() or not root.is_dir():
        return None
    return root.resolve()


def _safe_asset_path(root: Path, relative_file: str) -> Optional[Tuple[Path, str]]:
    if not relative_file:
        return None
    raw_path = Path(str(relative_file))
    if raw_path.is_absolute():
        return None
    candidate = (root / raw_path).resolve()
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return None
    if candidate.suffix.lower() not in EMOJI_EXTENSIONS:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate, str(relative)


def _safe_relative_path(root: Path, path: Path) -> Optional[str]:
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(root)
    except Exception:
        return None
    return str(relative)


def infer_legacy_metadata(relative_path: str) -> Dict[str, object]:
    joined = str(relative_path or "").lower()
    for reaction, hints in LEGACY_REACTION_HINTS:
        if any(str(hint).lower() in joined for hint in hints):
            return {
                "reactions": [reaction],
                "intensities": ["medium"],
                "stances": ["shared_with_user"],
                "topics": ["general"],
                "avoid_contexts": [],
                "weight": 1.0,
                "reviewed": True,
            }
    return {
        "reactions": ["approval"],
        "intensities": ["medium"],
        "stances": ["shared_with_user"],
        "topics": ["general"],
        "avoid_contexts": [],
        "weight": 0.3,
        "reviewed": False,
    }


def scan_legacy_emoji_assets(base_dir: str) -> List[EmojiAsset]:
    root = _resolve_root(base_dir)
    if root is None:
        return []

    assets = []
    seen_paths = set()
    for path in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
        if not path.is_file() or path.suffix.lower() not in EMOJI_EXTENSIONS:
            continue
        relative = _safe_relative_path(root, path)
        if relative is None:
            continue
        resolved = str(path.resolve())
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        metadata = infer_legacy_metadata(relative)
        assets.append(EmojiAsset(
            name=path.stem,
            path=str(path.resolve()),
            relative_path=relative,
            reactions=metadata["reactions"],
            intensities=metadata["intensities"],
            stances=metadata["stances"],
            topics=metadata["topics"],
            avoid_contexts=metadata["avoid_contexts"],
            weight=metadata["weight"],
            reviewed=bool(metadata["reviewed"]),
        ))
    return assets


def _load_manifest_json(manifest_path: Path, max_manifest_bytes: int) -> Optional[dict]:
    try:
        if manifest_path.stat().st_size > max_manifest_bytes:
            LOGGER.warning("emoji manifest skipped because it exceeds size limit")
            return None
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        LOGGER.warning("emoji manifest parse failed: %s", exc.__class__.__name__)
        return None


def _assets_from_manifest(root: Path, manifest: dict) -> List[EmojiAsset]:
    raw_assets = manifest.get("assets") if isinstance(manifest, dict) else {}
    if not isinstance(raw_assets, dict):
        return []

    assets = []
    seen_paths = set()
    for name, raw_item in raw_assets.items():
        if not isinstance(raw_item, dict):
            continue
        safe_path = _safe_asset_path(root, str(raw_item.get("file") or ""))
        if safe_path is None:
            continue
        path, relative = safe_path
        resolved = str(path.resolve())
        if resolved in seen_paths:
            continue
        seen_paths.add(resolved)
        assets.append(EmojiAsset(
            name=str(name or path.stem),
            path=resolved,
            relative_path=relative,
            reactions=list(raw_item.get("reactions") or []),
            intensities=list(raw_item.get("intensities") or []),
            stances=list(raw_item.get("stances") or []),
            topics=list(raw_item.get("topics") or []),
            avoid_contexts=list(raw_item.get("avoid_contexts") or []),
            weight=float(raw_item.get("weight", 1.0) or 0.0),
            reviewed=bool(raw_item.get("reviewed", True)),
        ))
    return assets


def load_emoji_catalog(base_dir: str, max_manifest_bytes: int = MAX_MANIFEST_BYTES) -> List[EmojiAsset]:
    root = _resolve_root(base_dir)
    if root is None:
        return []

    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return scan_legacy_emoji_assets(str(root))

    manifest = _load_manifest_json(manifest_path, max_manifest_bytes)
    if manifest is None:
        return scan_legacy_emoji_assets(str(root))
    return _assets_from_manifest(root, manifest)
