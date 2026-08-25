from typing import List

from .config import SourceConfig, load_source_config
from .sources.grok_bridge import GrokBridgeFootballSource
from .sources.legacy_portal import LegacyPortalFootballSource


def load_topic_packs(path: str = "") -> list:
    return list(load_source_config(path).topic_packs)


def build_default_sources(
    source_config: SourceConfig,
    legacy_sources: List[dict],
    legacy_fetcher,
    grok_api_url: str = "",
    grok_api_key: str = "",
) -> list:
    sources = [
        LegacyPortalFootballSource(source=source, fetcher=legacy_fetcher)
        for source in list(legacy_sources or [])
    ]
    if grok_api_url:
        sources.append(GrokBridgeFootballSource(api_url=grok_api_url, api_key=grok_api_key))
    return sources
