import re
from typing import List


ARTIFACT_MARKER_RE = re.compile(r"\[(?:RenderedImage|GeneratedImage|LinkSnapshotImage):\s*[^\]]+\]")
LEGACY_ARTIFACT_TOOL_NAMES = {
    "render_markdown_to_image",
    "render_text_to_tactical_board",
    "generate_image",
    "analyze_links",
    "grok_search",
    "verify_recent_claim",
    "web_search",
}


def extract_artifact_markers(text: str) -> List[str]:
    markers = []
    seen = set()
    for match in ARTIFACT_MARKER_RE.finditer(str(text or "")):
        marker = match.group(0)
        if marker not in seen:
            markers.append(marker)
            seen.add(marker)
    return markers


def legacy_artifacts_for_tool(tool_name: str, content: str) -> List[str]:
    if tool_name not in LEGACY_ARTIFACT_TOOL_NAMES:
        return []
    return extract_artifact_markers(content)

