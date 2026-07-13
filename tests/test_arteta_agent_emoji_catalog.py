import json
import subprocess
import sys
from pathlib import Path

from plugins.arteta_agent.emoji.catalog import load_emoji_catalog
from tools.build_emoji_manifest import build_emoji_manifest


def write_file(path: Path, content=b"image"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def write_manifest(root: Path, assets):
    (root / "manifest.json").write_text(
        json.dumps({"version": 1, "assets": assets}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_catalog_loads_tagged_manifest_assets(tmp_path):
    root = tmp_path / "emoji"
    write_file(root / "skeptical" / "arteta_stare_01.gif")
    write_manifest(root, {
        "arteta_stare_01": {
            "file": "skeptical/arteta_stare_01.gif",
            "reactions": ["skeptical", "speechless"],
            "intensities": ["medium"],
            "stances": ["toward_claim"],
            "topics": ["football", "meme"],
            "avoid_contexts": ["serious_injury"],
            "weight": 2.0,
        }
    })

    assets = load_emoji_catalog(str(root))

    assert len(assets) == 1
    assert assets[0].name == "arteta_stare_01"
    assert assets[0].relative_path == str(Path("skeptical") / "arteta_stare_01.gif")
    assert assets[0].path.endswith(str(Path("skeptical") / "arteta_stare_01.gif"))
    assert assets[0].reactions == ["skeptical", "speechless"]
    assert assets[0].weight == 2.0


def test_catalog_falls_back_to_legacy_scan_when_manifest_missing_or_broken(tmp_path):
    missing_root = tmp_path / "missing_manifest"
    write_file(missing_root / "开心" / "happy.png")
    write_file(missing_root / "思考" / "thinking.gif")
    write_file(missing_root / "消极" / "angry.webp")
    write_file(missing_root / "消极" / "震惊.png")
    write_file(missing_root / "unknown.png")

    broken_root = tmp_path / "broken_manifest"
    write_file(broken_root / "难过" / "sad.png")
    (broken_root / "manifest.json").write_text("{broken", encoding="utf-8")

    missing_assets = load_emoji_catalog(str(missing_root))
    broken_assets = load_emoji_catalog(str(broken_root))

    by_name = {asset.name: asset for asset in missing_assets}
    assert by_name["happy"].reactions == ["celebration"]
    assert by_name["thinking"].reactions == ["thinking"]
    assert by_name["angry"].reactions == ["frustrated"]
    assert by_name["震惊"].reactions == ["surprised"]
    assert by_name["unknown"].reactions == ["approval"]
    assert by_name["unknown"].weight == 0.3
    assert broken_assets[0].name == "sad"
    assert broken_assets[0].reactions == ["sad"]


def test_catalog_rejects_unsafe_manifest_entries(tmp_path):
    root = tmp_path / "emoji"
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    write_file(root / "valid" / "ok.png")
    write_file(root / "valid" / "same.gif")
    write_file(root / "valid" / "bad.txt")
    absolute_path = str(outside.resolve())
    write_manifest(root, {
        "valid": {"file": "valid/ok.png", "reactions": ["approval"]},
        "escape": {"file": "../outside.png", "reactions": ["teasing"]},
        "absolute": {"file": absolute_path, "reactions": ["sad"]},
        "text": {"file": "valid/bad.txt", "reactions": ["approval"]},
        "missing": {"file": "valid/missing.png", "reactions": ["approval"]},
        "duplicate_one": {"file": "valid/same.gif", "reactions": ["approval"]},
        "duplicate_two": {"file": "valid/same.gif", "reactions": ["sad"]},
    })

    assets = load_emoji_catalog(str(root))

    assert sorted(asset.name for asset in assets) == ["duplicate_one", "valid"]
    assert all(".." not in asset.relative_path for asset in assets)
    assert all(not Path(asset.relative_path).is_absolute() for asset in assets)


def test_catalog_oversized_manifest_falls_back_to_legacy_scan(tmp_path):
    root = tmp_path / "emoji"
    write_file(root / "开心" / "happy.png")
    (root / "manifest.json").write_text(" " * 64, encoding="utf-8")

    assets = load_emoji_catalog(str(root), max_manifest_bytes=16)

    assert len(assets) == 1
    assert assets[0].name == "happy"
    assert assets[0].reactions == ["celebration"]


def test_build_emoji_manifest_generates_initial_tags_without_overwriting_manual_labels(tmp_path):
    root = tmp_path / "emoji"
    output = root / "manifest.json"
    write_file(root / "开心" / "happy.png")
    write_file(root / "unknown" / "mystery.png")
    write_manifest(root, {
        "happy": {
            "file": "开心/happy.png",
            "reactions": ["approval"],
            "weight": 2.5,
        }
    })

    result = build_emoji_manifest(str(root), output_path=str(output), dry_run=True)

    assert result["manifest"]["assets"]["happy"]["reactions"] == ["approval"]
    assert result["manifest"]["assets"]["happy"]["weight"] == 2.5
    assert result["manifest"]["assets"]["mystery"]["reactions"] == ["approval"]
    assert "unknown/mystery.png" in result["unrecognized"]
    assert json.loads(output.read_text(encoding="utf-8"))["assets"]["happy"]["weight"] == 2.5


def test_build_emoji_manifest_cli_runs_from_repo_root(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    root = tmp_path / "emoji"
    write_file(root / "开心" / "happy.png")

    result = subprocess.run(
        [
            sys.executable,
            "tools/build_emoji_manifest.py",
            str(root),
            "--dry-run",
        ],
        cwd=str(repo_root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["manifest"]["assets"]["happy"]["reactions"] == ["celebration"]
