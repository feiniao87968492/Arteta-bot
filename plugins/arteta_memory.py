"""ChromaDB 群体记忆 - 持久化对话历史 + 语义检索"""

import logging
import os
import sys
import time
from datetime import datetime

# 系统 sqlite3 可能过旧（ChromaDB 要求 >= 3.35.0），使用 pysqlite3-binary 替代
try:
    import pysqlite3  # type: ignore
    sys.modules["sqlite3"] = pysqlite3
except ImportError:
    pass

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

CHROMA_DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chroma_db")
COLLECTION_NAME = "group_memories"
MAX_DOC_LENGTH = 1000  # 单条记忆的最大字符数
N_RESULTS = 5  # 每次检索返回条数


class MemoryStore:
    """ChromaDB 记忆存储封装，全局单例"""

    def __init__(self):
        self.client = None
        self.collection = None
        self._ready = False

    def initialize(self):
        """初始化 ChromaDB PersistentClient 和 collection"""
        try:
            self.client = chromadb.PersistentClient(
                path=CHROMA_DB_DIR,
                settings=Settings(anonymized_telemetry=False),
            )
            try:
                self.collection = self.client.get_collection(COLLECTION_NAME)
            except Exception:
                self.collection = self.client.create_collection(COLLECTION_NAME)
            self._ready = True
            logger.info(f"[MemoryStore] ChromaDB 初始化成功，数据目录: {CHROMA_DB_DIR}")
        except Exception as e:
            self._ready = False
            logger.error(f"[MemoryStore] ChromaDB 初始化失败: {e}")

    def add_memory(self, group_id: str, user_id: str, user_msg: str, assistant_reply: str):
        """将一轮对话存入 ChromaDB"""
        if not self._ready:
            return

        content = f"User: {user_msg}\nAssistant: {assistant_reply}"
        if len(content) > MAX_DOC_LENGTH:
            content = content[:MAX_DOC_LENGTH]

        ts = time.time()
        doc_id = f"{group_id}_{int(ts)}_{user_id[-8:]}"

        try:
            self.collection.add(
                documents=[content],
                metadatas=[{
                    "group_id": str(group_id),
                    "user_id": str(user_id),
                    "timestamp": ts,
                    "user_msg_preview": user_msg[:50],
                }],
                ids=[doc_id],
            )
        except Exception as e:
            logger.warning(f"[MemoryStore] add_memory 失败: {e}")

    def query_memories(self, group_id: str, query_text: str) -> list:
        """按语义检索本群相关历史对话，返回格式化字符串列表"""
        if not self._ready:
            return []

        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=N_RESULTS,
                where={"group_id": str(group_id)},
            )
        except Exception as e:
            logger.warning(f"[MemoryStore] query_memories 失败: {e}")
            return []

        if not results or not results["documents"] or not results["documents"][0]:
            return []

        formatted = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            ts = meta.get("timestamp", 0)
            date_str = datetime.fromtimestamp(ts).strftime("%m月%d日")
            formatted.append(f"--- {date_str} ---\n{doc}")

        return formatted


# 全局单例
memory_store = MemoryStore()
