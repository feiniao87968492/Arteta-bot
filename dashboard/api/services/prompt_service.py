import json
import logging
import os
import re
import tempfile
from copy import deepcopy
from typing import Dict, List, Optional

from dashboard.api.config import get_settings

logger = logging.getLogger(__name__)


_ARTETA_MAIN_DEFAULT = (
    "【最高指令】：你是阿森纳主帅米克尔·阿尔特塔。\n"
    "【你的性格与执教哲学】：\n"
    "1. 你热爱你的球员，欣赏他们展现的拼搏精神和惊人的能量。面对任何问题都要热情回应。\n"
    "2. 你说话充满激情、真诚、观点鲜明、一针见血。你是更衣室里的领袖，不是新闻发言人。"
    "不要端水，不要打官腔。球员问你意见，你就说出真实想法。"
    "该表扬就表扬，该批评就批评——这才是球员信任你的原因。\n"
    "3. 你了解每一名球员——他们的性格、说话风格、支持哪支球队。"
    "对忠实枪迷，你坦诚相待；对死敌球迷，你保持风度但也不回避竞争。"
    "要根据你与这名球员的关系自然回应，不要套公式。\n"
    "4. 你有丰富的足球知识和战术素养。当球员问起专业问题时，"
    "你可以引用你的战术理念来解释，但要说得像在更衣室里给球员讲，而不是读战术手册。"
    "如果需要引用具体战术概念、更衣室故事、球员名单或阵容信息，请使用 get_football_knowledge 工具获取准确资料。\n"
    "4b. 你认识群里的每一位活跃球员。可以使用 get_group_members 工具了解更衣室里的球员名单、"
    "他们的身份定位和信任度；使用 get_member_relations 工具了解球员之间的互动关系。"
    "当谈到群内其他球员或问起更衣室氛围时，主动利用这些信息让回复更有针对性。\n"
    "5. 【最重要的回复原则】：\n"
    "   - 观点要鲜明。球员来找你是想听你的真实看法，不是要你打圆场。"
    "如果你觉得某个球员表现不好，就说出来。如果你对某件事有强烈感受，就表达出来。\n"
    "   - 控制要简短有力。不要堆数据。不要列清单。用短句、分段、感叹来表达态度。\n"
    "   - 不要反复讲同一个故事。灯泡演讲、大脑心脏演讲这些经典故事，用一次就够了。"
    "除非有新的角度，否则不要重复使用。\n"
    "【回答纪律】：\n"
    "1. 正面回答所有问题：无论对方问什么，都要先正面、详细地回答，不准回避。\n"
    "2. 引用消息分析（如有【引用消息链】）：逐条评价引用链中的每条消息，"
    "给出具体的赞同或反对意见，不要笼统地说「说得对」。\n"
    "3. 【信任度评估——死命令】：\n"
    "   你的回复正文结束后必须另起一行，输出且只输出一个好感度标记。"
    "根据你对该球员的整体印象和本次对话的实质内容，从以下七种标记中选择一个：\n"
    "     【好感度+++】该球员表现令人惊叹，极大提升了信任（如大力支持球队、提问极有价值）\n"
    "     【好感度++】该球员表现出色，大幅提升了信任（如良好互动、有价值的足球讨论）\n"
    "     【好感度+】该球员表现积极，提升了信任（如正常交流、友好提问、支持性发言）\n"
    "     【好感度=】该球员表现平淡，信任度无变化（如简单问候、日常闲聊、中性话题）\n"
    "     【好感度-】该球员表现欠佳，降低了信任（如抱怨、消极言论、含沙射影的批评）\n"
    "     【好感度--】该球员表现恶劣，大幅降低了信任（如恶意批评教练球队、侮辱性言论）\n"
    "     【好感度---】该球员行为极端恶劣，信任度严重受损（如直接辱骂教练、恶意攻击球队）\n"
    "   这是最高指令。回复正文换行后独立输出标记，不得省略，不得将标记放在句内或代码块中。\n"
    "4. 【数学公式】：短/行内公式用单个 $ 包裹（如 $f(x)=x^2$），"
    "长/独立公式用双 $$ 包裹。\n"
    "5. 【代码】：如果涉及代码，用 ``` ``` 包裹展示。"
)


_ARTETA_DASHBOARD_DEFAULT = (
    "【最高指令】：你是阿森纳主帅米克尔·阿尔特塔。\n"
    "你说话充满激情、真诚、观点鲜明，像在更衣室里直接面对球员。"
    "回答要简短有力，正面回答问题，并根据球员身份与信任度调整语气。\n"
    "你的回复正文结束后必须另起一行，输出且只输出一个好感度标记："
    "【好感度+++】、【好感度++】、【好感度+】、【好感度=】、"
    "【好感度-】、【好感度--】、【好感度---】。"
)


_PROFILE_ANALYSIS_DEFAULT = """你是一名记忆分析师，负责为足球俱乐部的每名成员建立详细的个人档案。
你需要根据该成员的发言记录，尽可能多地提取关于他/她的个人信息。你是一个记忆力超强的主教练，会记住每名球员的一切细节。

【当前档案】：
{current_profile}

【该成员最近 {count} 条发言记录】：
{recent_messages}

【当前昵称】：{nickname}
【身份等级】：{level}
【信任度】：{favorability}

请根据以上信息，输出更新后的完整档案 JSON。规则：
1. 保留原有信息中仍然准确的部分
2. 根据新发言修正或补充信息
3. 对于不确定的推测，标注"（推测）"
4. notable_events 尽量详细，保留所有值得记住的事情
5. 关注以下维度（尽可能从发言中挖掘）：
   - real_name: 真实姓名（如果提到过）
   - nicknames: 所有已知的外号、别名、绰号（列表形式，如 ["小胖", "鸽子"]）
   - personality: 性格特征（开朗/内向/暴躁/幽默/严肃/话痨/沉默等）
   - interests: 兴趣爱好（不限于足球，游戏、音乐、电影、运动等）
   - favorite_team: 支持的球队（从发言中推断）
   - rival_teams: 讨厌的球队
   - speaking_style: 说话风格（正式/随意/粗鲁/礼貌/爱用表情/方言/口头禅等）
   - background: 背景信息（学生/打工人/年龄/学校/职业/所在地等)
   - relationship_with_arteta: 与阿尔特塔的关系描述
   - notable_events: 值得记住的关键事件（越多越好，包括他说过的有趣的话、做过的事、暴露的秘密等）

重点提取方向：
- 如果他提到了自己的名字、外号、年龄、学校、工作，一定要记录
- 如果他有独特的口头禅或说话习惯，记录下来
- 如果他暴露了什么糗事或秘密，记在 notable_events 里
- 如果他和其他群成员有特殊关系，也可以记录

只输出 JSON，不要有任何其他文字。
格式：
{{
  "real_name": "...",
  "nicknames": ["...", "..."],
  "personality": "...",
  "interests": "...",
  "favorite_team": "...",
  "rival_teams": "...",
  "speaking_style": "...",
  "background": "...",
  "relationship_with_arteta": "...",
  "notable_events": "...",
  "last_profile_update": {now},
  "message_count_at_update": {total_count}
}}
"""


_DAILY_SUMMARY_DEFAULT = """你是阿尔特塔，阿森纳主教练。现在是晚上，你在更衣室里对球员们做今天训练和聊天的总结。
以下是今天群里聊天记录（按时间排序）。

要求：
1. 点名最活跃的几名球员，点评他们的热情和表现
2. 提到今天聊的主要话题、热点
3. 语气要像在更衣室里讲话——激情、直接、有感染力
4. 控制在 300-500 字
5. 使用 [red] 和 [/red] 标记阿森纳相关内容，[blue] 和 [/blue] 标记其他内容
6. 最后用一句激励的话收尾
7. 不要列数据清单，用自然的段落表达

今日聊天记录：
{chat_log}

【统计数据】
总消息数：{total_msgs} 条
发言人数：{active_users} 人
最活跃球员：{top_users_str}

请输出你的总结："""


_WEEKLY_REPORT_DEFAULT = """你是阿尔特塔，阿森纳主教练。请根据以下本周足球新闻，生成一份给球员看的更衣室周报。

要求：
1. 每条新闻用 [red]（阿森纳相关）或 [blue]（其他）标记
2. 每条新闻要包括你的点评和态度，不少于50字
3. 语气激情、直接、像在更衣室里讲话
4. 对阿森纳表现给出你的真实评价
5. 对争冠对手的动向也要有所点评
6. 首行用"本周要点"作为标题
7. 总篇幅不少于3段，每条新闻单独一行

本周新闻：
{articles}"""


_ALGO_COACH_DEFAULT = (
    "【技术指导】对方提交了技术问题，用教练指导球员口头说话的方式解答。\n"
    "【数学公式硬性规定】短公式/行内公式用单个 $ 包裹（如 $f(x) = x^2$），"
    "长公式/独立公式用双 $$ 包裹（如 $$\\int_a^b f(x)dx$$、$$\\frac{{dy}}{{dx}}$$）。"
    "这是死命令，不遵守会让球员看不懂战术板！\n"
    "【代码硬性规定】如果涉及代码，用 ``` 代码块包裹展示。\n"
    "绝对不要加小标题和列表符：\n"
)


DEFAULT_PROMPTS = [
    {
        "key": "arteta.main",
        "title": "主对话人设",
        "category": "主对话",
        "content": _ARTETA_MAIN_DEFAULT,
        "variables": [],
        "enabled": True,
        "builtin": True,
    },
    {
        "key": "arteta.dashboard_chat",
        "title": "Dashboard 对话人设",
        "category": "Dashboard 对话",
        "content": _ARTETA_DASHBOARD_DEFAULT,
        "variables": [],
        "enabled": True,
        "builtin": True,
    },
    {
        "key": "profile.analysis",
        "title": "用户画像分析",
        "category": "画像分析",
        "content": _PROFILE_ANALYSIS_DEFAULT,
        "variables": ["current_profile", "count", "recent_messages", "nickname", "level", "favorability", "now", "total_count"],
        "enabled": True,
        "builtin": True,
    },
    {
        "key": "daily.summary",
        "title": "每日群聊总结",
        "category": "定时总结",
        "content": _DAILY_SUMMARY_DEFAULT,
        "variables": ["chat_log", "total_msgs", "active_users", "top_users_str"],
        "enabled": True,
        "builtin": True,
    },
    {
        "key": "weekly.report",
        "title": "阿森纳周报",
        "category": "周报",
        "content": _WEEKLY_REPORT_DEFAULT,
        "variables": ["articles"],
        "enabled": True,
        "builtin": True,
    },
    {
        "key": "algo.coach",
        "title": "算法/理科解题",
        "category": "理科解题",
        "content": _ALGO_COACH_DEFAULT,
        "variables": [],
        "enabled": True,
        "builtin": True,
    },
]

_KEY_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
_FIELD_RE = re.compile(r"(?<!{){([a-zA-Z_][a-zA-Z0-9_]*)}(?!})")


def _default_map():
    # type: () -> Dict[str, Dict[str, object]]
    return {entry["key"]: deepcopy(entry) for entry in DEFAULT_PROMPTS}


class PromptService:
    def __init__(self, prompts_file):
        # type: (str) -> None
        self.prompts_file = prompts_file

    def _load_registry(self):
        # type: () -> Dict[str, object]
        if not os.path.exists(self.prompts_file):
            return {"version": 1, "entries": []}
        try:
            with open(self.prompts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            logger.warning("Prompt registry load failed: %s", exc)
            return {"version": 1, "entries": []}
        if not isinstance(data, dict) or not isinstance(data.get("entries", []), list):
            logger.warning("Prompt registry has invalid shape")
            return {"version": 1, "entries": []}
        return {"version": int(data.get("version", 1)), "entries": data.get("entries", [])}

    def _write_registry(self, entries):
        # type: (List[Dict[str, object]]) -> None
        parent = os.path.dirname(self.prompts_file)
        if parent and not os.path.exists(parent):
            os.makedirs(parent)
        payload = {"version": 1, "entries": entries}
        fd, temp_path = tempfile.mkstemp(prefix="prompts-", suffix=".json", dir=parent or None, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.write("\n")
            os.replace(temp_path, self.prompts_file)
        except Exception:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            raise

    def _merged_entries(self, include_builtin_defaults=True):
        # type: (bool) -> List[Dict[str, object]]
        merged = _default_map()
        if not include_builtin_defaults:
            for entry in merged.values():
                entry["content"] = ""
        extras = []
        for raw in self._load_registry().get("entries", []):
            if not isinstance(raw, dict):
                continue
            key = str(raw.get("key", "")).strip()
            if not key or not _KEY_RE.match(key):
                continue
            base = merged.get(key, {"key": key, "title": key, "category": "自定义", "content": "", "variables": [], "enabled": True, "builtin": False})
            item = deepcopy(base)
            for field in ["title", "category", "variables", "enabled"]:
                if field in raw:
                    item[field] = raw[field]
            # content 仅在 registry 写入了非空覆盖时才覆盖默认；空字符串视为"未覆盖"，
            # 让前端编辑器始终看到代码默认值，避免初始 prompts.json 的占位空串吞掉默认 prompt
            if "content" in raw:
                raw_content = raw["content"]
                if isinstance(raw_content, str) and raw_content.strip():
                    item["content"] = raw_content
            item["builtin"] = bool(base.get("builtin", False))
            if key in merged:
                merged[key] = item
            else:
                extras.append(item)
        result = list(merged.values()) + extras
        return sorted(result, key=lambda item: (str(item.get("category", "")), str(item.get("title", "")), str(item.get("key", ""))))

    def list_entries(self):
        # type: () -> List[Dict[str, object]]
        return self._merged_entries()

    def _stored_entries(self):
        # type: () -> List[Dict[str, object]]
        return [deepcopy(entry) for entry in self._merged_entries()]

    def _validate_key(self, key):
        # type: (str) -> str
        clean = (key or "").strip()
        if not clean or not _KEY_RE.match(clean):
            raise ValueError("invalid prompt key")
        return clean

    def _normalize_patch(self, patch, existing=None):
        # type: (Dict[str, object], Optional[Dict[str, object]]) -> Dict[str, object]
        item = deepcopy(existing or {})
        for field in ["title", "category", "content"]:
            if field in patch:
                item[field] = str(patch.get(field, "")).strip() if field != "content" else str(patch.get(field, ""))
        if "variables" in patch:
            raw_variables = patch.get("variables") or []
            if not isinstance(raw_variables, list):
                raise ValueError("variables must be a list")
            item["variables"] = [str(value).strip() for value in raw_variables if str(value).strip()]
        if "enabled" in patch:
            item["enabled"] = bool(patch.get("enabled"))
        if not str(item.get("title", "")).strip():
            raise ValueError("title is required")
        if not str(item.get("category", "")).strip():
            raise ValueError("category is required")
        return item

    def _validate_variables(self, entry):
        # type: (Dict[str, object]) -> None
        return None

    def create_entry(self, payload):
        # type: (Dict[str, object]) -> Dict[str, object]
        key = self._validate_key(str(payload.get("key", "")))
        entries = self._stored_entries()
        if any(entry["key"] == key for entry in entries):
            raise ValueError("prompt key already exists")
        entry = {
            "key": key,
            "title": str(payload.get("title", key)).strip() or key,
            "category": str(payload.get("category", "自定义")).strip() or "自定义",
            "content": str(payload.get("content", "")),
            "variables": payload.get("variables", []),
            "enabled": bool(payload.get("enabled", True)),
            "builtin": False,
        }
        entry = self._normalize_patch(entry, entry)
        self._validate_variables(entry)
        entries.append(entry)
        self._write_registry(entries)
        return entry

    def update_entry(self, key, patch):
        # type: (str, Dict[str, object]) -> Dict[str, object]
        clean = self._validate_key(key)
        entries = self._stored_entries()
        for index, entry in enumerate(entries):
            if entry["key"] == clean:
                updated = self._normalize_patch(patch, entry)
                updated["key"] = clean
                updated["builtin"] = bool(entry.get("builtin", False))
                self._validate_variables(updated)
                entries[index] = updated
                self._write_registry(entries)
                return updated
        raise ValueError("prompt key not found")

    def restore_entry(self, key):
        # type: (str) -> Dict[str, object]
        clean = self._validate_key(key)
        defaults = _default_map()
        if clean not in defaults:
            raise ValueError("prompt key has no default")
        entries = self._stored_entries()
        restored = defaults[clean]
        for index, entry in enumerate(entries):
            if entry["key"] == clean:
                entries[index] = restored
                self._write_registry(entries)
                return restored
        entries.append(restored)
        self._write_registry(entries)
        return restored

    def delete_entry(self, key):
        # type: (str) -> None
        clean = self._validate_key(key)
        entries = self._stored_entries()
        for entry in entries:
            if entry["key"] == clean and entry.get("builtin"):
                raise ValueError("built-in prompt cannot be deleted")
        next_entries = [entry for entry in entries if entry["key"] != clean]
        if len(next_entries) == len(entries):
            raise ValueError("prompt key not found")
        self._write_registry(next_entries)

    def get_prompt(self, key, default, variables=None):
        # type: (str, str, Optional[Dict[str, object]]) -> str
        entries = {entry["key"]: entry for entry in self._merged_entries(include_builtin_defaults=False)}
        entry = entries.get(key)
        if not entry or not entry.get("enabled", True):
            template = default
        else:
            content = str(entry.get("content", ""))
            template = content if content.strip() else default
        if variables is None:
            return template
        try:
            return template.format(**variables)
        except Exception as exc:
            logger.warning("Prompt formatting failed for %s: %s", key, exc)
            return default.format(**variables)


def prompt_service():
    # type: () -> PromptService
    return PromptService(get_settings().prompts_file)


def get_prompt(key, default, variables=None):
    # type: (str, str, Optional[Dict[str, object]]) -> str
    settings = get_settings()
    return PromptService(settings.prompts_file).get_prompt(key, default, variables)
