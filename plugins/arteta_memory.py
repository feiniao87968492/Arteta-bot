"""ChromaDB 群体记忆 - 持久化对话历史 + 语义检索"""

import logging
import os
import sys
import time
from datetime import datetime

# 系统 sqlite3 可能过旧（ChromaDB 要求 >= 3.35.0），使用 pysqlite3-binary 替代
try:
    import pysqlite3  # type: ignore
except ImportError:
    pysqlite3 = None

if pysqlite3 is not None and callable(getattr(pysqlite3, "connect", None)) and all(
    hasattr(pysqlite3, name)
    for name in (
        "DatabaseError",
        "Error",
        "IntegrityError",
        "NotSupportedError",
        "OperationalError",
        "ProgrammingError",
        "Row",
        "Warning",
        "sqlite_version_info",
    )
):
    sys.modules["sqlite3"] = pysqlite3

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

CHROMA_DB_DIR = os.environ.get(
    "ARTETA_CHROMA_DIR",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "chroma_db"),
)
COLLECTION_NAME = "group_memories"
MAX_DOC_LENGTH = 1000  # 单条记忆的最大字符数
N_RESULTS = 5  # 每次检索返回条数


def _dedupe_aliases(nickname: str, aliases: list) -> list:
    seen = set()
    normalized = []
    for item in [nickname] + list(aliases or []):
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def build_memory_document(user_id: str, nickname: str, aliases: list, user_msg: str, assistant_reply: str) -> str:
    alias_list = _dedupe_aliases(nickname, aliases)
    alias_text = "、".join(alias_list) if alias_list else nickname
    return (
        f"Speaker ID: {user_id}\n"
        f"Speaker Nickname: {nickname}\n"
        f"Speaker Aliases: {alias_text}\n"
        f"User: {user_msg}\n"
        f"Assistant: {assistant_reply}"
    )


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

    def add_memory(self, group_id: str, user_id: str, user_msg: str, assistant_reply: str,
                   nickname: str = "", aliases: list = None):
        """将一轮对话存入 ChromaDB，确保 User 和 Assistant 两部分都被保留。"""
        if not self._ready:
            return

        content = build_memory_document(user_id, nickname or user_id, aliases or [], user_msg, assistant_reply)
        if len(content) > MAX_DOC_LENGTH:
            # 不再简单从末尾截断（会丢掉 Assistant 发言），改为分别截断两部分
            header = build_memory_document(user_id, nickname or user_id, aliases or [], "", "")
            header_len = len(header)
            available = MAX_DOC_LENGTH - header_len
            # 给 Assistant 留更多空间（60%），因为大模型回复通常比用户消息更长
            user_budget = max(20, int(available * 0.4))
            asst_budget = max(20, available - user_budget)
            truncated_user = user_msg[:user_budget] + ("..." if len(user_msg) > user_budget else "")
            truncated_asst = assistant_reply[:asst_budget] + ("..." if len(assistant_reply) > asst_budget else "")
            content = build_memory_document(user_id, nickname or user_id, aliases or [], truncated_user, truncated_asst)
            # 兜底：如果仍然超长（罕见），再从末尾硬截断
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

    def clear_group_memories(self, group_id: str) -> int:
        """清除指定群的长期对话记忆，返回删除条数"""
        if not self._ready:
            return 0

        try:
            existing = self.collection.get(
                where={"group_id": str(group_id)},
                include=[],
            )
            ids = list(existing.get("ids") or [])
            if not ids:
                return 0
            self.collection.delete(ids=ids)
            return len(ids)
        except Exception as e:
            logger.warning(f"[MemoryStore] clear_group_memories 失败: {e}")
            return 0


# 全局单例
memory_store = MemoryStore()
