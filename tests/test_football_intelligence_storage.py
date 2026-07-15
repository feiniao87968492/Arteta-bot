import tempfile
from pathlib import Path

from plugins.arteta_football_intelligence.storage import FootballNewsSQLiteStore
from plugins.arteta_football_intelligence.vector_index import build_item_chroma_id, repair_pending_indexes


class StorageItem(object):
    def __init__(self):
        self.title = "Arsenal confirm injury update"
        self.url = "https://www.arsenal.com/news/injury-update"
        self.source = "Arsenal"
        self.category = "premier_league"
        self.summary = "A first-team player has returned to training."
        self.published_at = 1716400000
        self.fetched_at = 1716400300
        self.content_hash = "abc123"

    def with_hash(self):
        return self


def test_sqlite_store_tracks_pending_ready_and_failed_index_status():
    item = StorageItem()
    chroma_id = build_item_chroma_id(item)

    with tempfile.TemporaryDirectory() as tmpdir:
        store = FootballNewsSQLiteStore(str(Path(tmpdir) / "news.db"))
        store.initialize()

        inserted = store.insert_pending_item(item, chroma_id)
        assert inserted is True
        rows = store.list_items_by_index_status("pending")
        assert [row["title"] for row in rows] == [item.title]

        store.mark_index_status(chroma_id, "ready")
        assert store.list_items_by_index_status("pending") == []
        assert [row["index_status"] for row in store.list_recent_items(days=90, now=1716400400)] == ["ready"]

        store.mark_index_status(chroma_id, "failed")
        assert [row["index_status"] for row in store.list_items_by_index_status("failed")] == ["failed"]


def test_build_item_chroma_id_is_stable_from_fetch_time_and_hash():
    item = StorageItem()

    assert build_item_chroma_id(item) == "football_news_item_1716400300_abc123"


def test_repair_pending_indexes_rebuilds_chroma_from_sqlite_rows():
    item = StorageItem()
    chroma_id = build_item_chroma_id(item)

    class RecordingChromaStore(object):
        def __init__(self):
            self.items = []

        def add_item(self, value):
            self.items.append(value)
            return build_item_chroma_id(value)

    with tempfile.TemporaryDirectory() as tmpdir:
        store = FootballNewsSQLiteStore(str(Path(tmpdir) / "news.db"))
        store.initialize()
        assert store.insert_pending_item(item, chroma_id) is True

        chroma = RecordingChromaStore()
        result = repair_pending_indexes(store, chroma)

        assert result == {"attempted": 1, "repaired": 1, "failed": 0}
        assert [value.title for value in chroma.items] == [item.title]
        assert store.list_items_by_index_status("pending") == []
        assert [row["index_status"] for row in store.list_recent_items(days=90, now=1716400400)] == ["ready"]
