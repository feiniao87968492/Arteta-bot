from typing import Iterable, Optional

from ..trace import format_trace_block


def compose_final_response(
    content: str,
    artifacts: Optional[Iterable[str]] = None,
    trace=None,
) -> str:
    output = str(content or "")
    for marker in list(artifacts or []):
        if marker and marker not in output:
            output = "{0}\n{1}".format(output.strip(), marker).strip()
    return output


def compose_trace_response(trace) -> str:
    return format_trace_block(trace) or "[Agent Trace]\ntools: none"


def compose_current_information_unavailable_response() -> str:
    return "这个问题依赖当前比赛或新闻信息，但这次联网查询没有获得可靠结果，我现在无法核实。"
