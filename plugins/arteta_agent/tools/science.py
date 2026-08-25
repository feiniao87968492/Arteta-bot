from ..context import ToolContext
from ..registry import ToolSpec, ensure_tool


def _get_arteta_chat():
    from plugins import arteta_chat

    return arteta_chat


def _build_user_text(ctx: ToolContext, question: str) -> str:
    parts = [str(question or ctx.raw_message or "").strip()]
    if ctx.reply_text:
        parts.append("【引用消息】\n" + ctx.reply_text)
    if ctx.image_analysis:
        parts.append("【图片内容】\n" + ctx.image_analysis)
    return "\n\n".join(part for part in parts if part)


def _with_subject_context(user_text: str, subject: str) -> str:
    subject_text = str(subject or "general").strip() or "general"
    return "题目类型：{0}\n\n{1}".format(subject_text, user_text)


async def solve_science_question(ctx: ToolContext, question: str = "", subject: str = "general") -> str:
    system_prompt = (
        "你是阿尔特塔式技术教练，负责解答数学、物理、算法和代码问题。"
        "请给出可执行推理，公式用 Markdown/LaTeX，代码用 fenced code block。"
    )
    user_text = _build_user_text(ctx, question)
    if not user_text:
        return "请提供要解答的题目。"
    return await _get_arteta_chat().call_algo_llm(system_prompt, _with_subject_context(user_text, subject))


async def solve_code_question(ctx: ToolContext, question: str = "", language: str = "") -> str:
    subject = "code"
    if language:
        subject += " / " + str(language)
    return await solve_science_question(ctx, question=question, subject=subject)


async def solve_algorithm_problem(ctx: ToolContext, question: str = "", language: str = "") -> str:
    # Registry wrapper for legacy /算法-style capability. The old command and
    # the agent tool share this path so behavior stays consistent.
    subject = "algorithm"
    if language:
        subject += " / " + str(language)
    return await solve_science_question(ctx, question=question, subject=subject)


async def solve_math_question(ctx: ToolContext, question: str = "") -> str:
    return await solve_science_question(ctx, question=question, subject="math")


def register_tools() -> None:
    base_schema = {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "用户要解答的题目，默认使用原始消息"},
            "subject": {"type": "string", "description": "题目类型，如 physics/math/algorithm/code"},
        },
        "required": [],
    }
    ensure_tool(ToolSpec(
        name="solve_science_question",
        description="解答数学、物理、算法、代码等技术题，只返回答案文本，不直接发送 QQ 消息。",
        parameters=base_schema,
        handler=solve_science_question,
        permission="safe_write",
        category="science",
        timeout_seconds=100.0,
    ))
    ensure_tool(ToolSpec(
        name="solve_algorithm_problem",
        description="解答算法、LeetCode、数据结构题，只返回答案文本，不直接发送 QQ 消息。",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "算法题或代码题"},
                "language": {"type": "string", "description": "可选编程语言"},
            },
            "required": [],
        },
        handler=solve_algorithm_problem,
        permission="safe_write",
        category="science",
        timeout_seconds=100.0,
    ))
    ensure_tool(ToolSpec(
        name="solve_code_question",
        description="解答代码、算法、LeetCode 类问题，只返回答案文本。",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "代码或算法题"},
                "language": {"type": "string", "description": "可选编程语言"},
            },
            "required": [],
        },
        handler=solve_code_question,
        permission="safe_write",
        category="science",
        timeout_seconds=100.0,
    ))
    ensure_tool(ToolSpec(
        name="solve_math_question",
        description="解答数学题，只返回答案文本。",
        parameters={
            "type": "object",
            "properties": {"question": {"type": "string", "description": "数学题"}},
            "required": [],
        },
        handler=solve_math_question,
        permission="safe_write",
        category="science",
        timeout_seconds=100.0,
    ))
