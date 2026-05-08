"""本地知识库检索引擎"""

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

KNOWLEDGE_BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge_base")

# 文件缓存：避免每次查询都读磁盘
_file_cache: Dict[str, str] = {}
_cache_loaded = False


def _load_all_files():
    """加载知识库所有 .md 文件到缓存"""
    global _cache_loaded
    if _cache_loaded:
        return
    kb_path = Path(KNOWLEDGE_BASE_DIR)
    if not kb_path.exists():
        _cache_loaded = True
        return
    for fpath in kb_path.rglob("*.md"):
        try:
            _file_cache[str(fpath.relative_to(kb_path))] = fpath.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("读取知识库文件失败: %s — %s", fpath, e)
    _cache_loaded = True


def clear_cache():
    """清除知识库文件缓存，下次查询时将重新从磁盘加载。"""
    global _cache_loaded
    _cache_loaded = False
    _file_cache.clear()


def query_knowledge(topic: str, max_chars: int = 1500) -> str:
    """根据主题关键词检索知识库，返回匹配的知识片段（原始内容，非摘要）。

    Args:
        topic: 搜索主题（中文关键词，如"边后卫""灯泡演讲""信任"）
        max_chars: 返回内容上限，超出时截取匹配段落附近的文本

    Returns:
        匹配的知识片段，无匹配时返回空字符串
    """
    _load_all_files()
    if not _file_cache:
        return ""

    topic_lower = topic.lower()

    # 评分：按关键词匹配度给分
    scored: List[Tuple[int, str, str]] = []  # (score, filename, content)

    for fname, content in _file_cache.items():
        content_lower = content.lower()
        score = 0

        # 文件名匹配（权重高）
        if topic_lower in fname.lower():
            score += 10

        # 在内容中的匹配次数
        matches = content_lower.count(topic_lower)
        score += matches * 2

        # ## 标题匹配（权重更高）
        for line in content.split("\n"):
            if line.startswith("##") and topic_lower in line.lower():
                score += 5
            if line.startswith("# ") and topic_lower in line.lower():
                score += 3

        if score > 0:
            scored.append((score, fname, content))

    if not scored:
        return ""

    # 按分数降序
    scored.sort(key=lambda x: x[0], reverse=True)

    # 返回最高分的文件内容摘要
    _, fname, content = scored[0]
    header = f"[知识来源：{fname}]\n"

    if len(content) <= max_chars:
        return header + content

    # 截取匹配段落附近的文本
    paragraphs = content.split("\n\n")
    topic_paragraphs = []
    remained = max_chars - len(header)
    for para in paragraphs:
        if topic_lower in para.lower():
            if len(para) <= remained:
                topic_paragraphs.append(para)
                remained -= len(para)
            else:
                topic_paragraphs.append(para[:remained])
                break

    if topic_paragraphs:
        return header + "\n\n".join(topic_paragraphs)
    else:
        return header + content[:max_chars]


def get_knowledge_file_list() -> List[str]:
    """返回知识库文件列表（供调试/查看用）"""
    _load_all_files()
    return sorted(_file_cache.keys())
