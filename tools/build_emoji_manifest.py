import argparse
import json
import sys
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.arteta_agent.emoji.catalog import EMOJI_EXTENSIONS, infer_legacy_metadata


def _relative_manifest_path(root: Path, path: Path) -> str:
    return "/".join(path.resolve().relative_to(root.resolve()).parts)


def _load_existing_manifest(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {"version": 1, "assets": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "assets": {}}
    if not isinstance(data, dict):
        return {"version": 1, "assets": {}}
    if not isinstance(data.get("assets"), dict):
        data["assets"] = {}
    data["version"] = int(data.get("version") or 1)
    return data


def _unique_asset_name(assets: Dict[str, object], path: Path) -> str:
    base = path.stem
    if base not in assets:
        return base
    index = 2
    while "{0}_{1}".format(base, index) in assets:
        index += 1
    return "{0}_{1}".format(base, index)


def build_emoji_manifest(base_dir: str, output_path: str = "", dry_run: bool = False) -> Dict[str, object]:
    root = Path(base_dir).resolve()
    manifest_path = Path(output_path).resolve() if output_path else root / "manifest.json"
    manifest = _load_existing_manifest(manifest_path)
    assets = dict(manifest.get("assets") or {})
    unrecognized = []

    for path in sorted(root.rglob("*"), key=lambda item: str(item).lower()):
        if not path.is_file() or path.suffix.lower() not in EMOJI_EXTENSIONS:
            continue
        if path.resolve() == manifest_path:
            continue
        relative = _relative_manifest_path(root, path)
        existing = None
        for raw_item in assets.values():
            if isinstance(raw_item, dict) and raw_item.get("file") == relative:
                existing = raw_item
                break
        if existing is not None:
            continue
        metadata = infer_legacy_metadata(relative)
        if not metadata.get("reviewed"):
            unrecognized.append(relative)
        name = _unique_asset_name(assets, path)
        assets[name] = {
            "file": relative,
            "reactions": metadata["reactions"],
            "intensities": metadata["intensities"],
            "stances": metadata["stances"],
            "topics": metadata["topics"],
            "avoid_contexts": metadata["avoid_contexts"],
            "weight": metadata["weight"],
            "reviewed": metadata["reviewed"],
        }

    result_manifest = {
        "version": int(manifest.get("version") or 1),
        "assets": assets,
    }
    result = {
        "manifest": result_manifest,
        "unrecognized": unrecognized,
    }
    if not dry_run:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(result_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an initial Arteta emoji manifest from a whitelist directory.")
    parser.add_argument("base_dir", help="ARTETA_EMOJI_DIR-compatible emoji directory")
    parser.add_argument("--output", default="", help="manifest output path; defaults to <base_dir>/manifest.json")
    parser.add_argument("--dry-run", action="store_true", help="print generated manifest without writing")
    args = parser.parse_args()
    result = build_emoji_manifest(args.base_dir, output_path=args.output, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
