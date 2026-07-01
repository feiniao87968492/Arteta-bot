import os
import sys
from typing import Any, Dict, List


def _install_pysqlite3() -> None:
    try:
        import pysqlite3  # type: ignore
    except ImportError:
        return
    sys.modules["sqlite3"] = pysqlite3


class ChromaService:
    def __init__(self, chroma_dir: str):
        self.chroma_dir = chroma_dir
        self.collection_name = "group_memories"

    def _collection(self):
        _install_pysqlite3()
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(path=self.chroma_dir, settings=Settings(anonymized_telemetry=False))
        return client.get_collection(self.collection_name)

    def health(self) -> Dict[str, object]:
        if not os.path.isdir(self.chroma_dir):
            return {"available": False, "collection": self.collection_name, "count": 0}
        try:
            collection = self._collection()
            return {"available": True, "collection": self.collection_name, "count": collection.count()}
        except Exception as exc:
            return {"available": False, "collection": self.collection_name, "error": str(exc), "count": 0}

    def list_memories(self, group_id: str = "", limit: int = 100) -> List[Dict[str, object]]:
        collection = self._collection()
        where = {"group_id": group_id} if group_id else None
        result = collection.get(where=where, limit=limit, include=["documents", "metadatas"])
        return self._rows(result)

    def query(self, group_id: str, text: str, limit: int = 10) -> List[Dict[str, object]]:
        collection = self._collection()
        where = {"group_id": group_id} if group_id else None
        result = collection.query(
            query_texts=[text],
            n_results=limit,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        rows = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for idx, doc_id in enumerate(ids):
            document = docs[idx] if idx < len(docs) else ""
            metadata = metas[idx] if idx < len(metas) else {}
            distance = distances[idx] if idx < len(distances) else None
            rows.append({"id": doc_id, "document": document, "metadata": metadata, "distance": distance})
        return rows

    def get_memories_by_ids(self, ids: List[str]) -> List[Dict[str, object]]:
        collection = self._collection()
        result = collection.get(ids=ids, include=["documents", "metadatas"])
        return self._rows(result)

    def delete(self, ids: List[str]) -> int:
        collection = self._collection()
        collection.delete(ids=ids)
        return len(ids)

    def _rows(self, result: Dict[str, Any]) -> List[Dict[str, object]]:
        rows = []
        ids = result.get("ids", [])
        docs = result.get("documents", [])
        metas = result.get("metadatas", [])
        for idx, doc_id in enumerate(ids):
            document = docs[idx] if idx < len(docs) else ""
            metadata = metas[idx] if idx < len(metas) else {}
            rows.append({"id": doc_id, "document": document, "metadata": metadata, "preview": document[:120]})
        return rows
