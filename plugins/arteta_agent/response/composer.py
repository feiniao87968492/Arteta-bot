from typing import Iterable, Optional

from ..trace import format_trace_block


def trace_has_marker(trace, marker: str) -> bool:
    if not trace:
        return False
    for item in trace.get("tools") or []:
        if marker in (item.get("markers") or []):
            return True
    return False


def prefix_trace_markers(value: str, trace=None) -> str:
    text = str(value or "")
    if trace_has_marker(trace, "[grok]") and not text.lstrip().startswith("[grok]"):
        return "[grok]\n" + text
    return text


def compose_final_response(
    content: str,
    artifacts: Optional[Iterable[str]] = None,
    trace=None,
) -> str:
    output = str(content or "")
    for marker in list(artifacts or []):
        if marker and marker not in output:
            output = "{0}\n{1}".format(output.strip(), marker).strip()
    return prefix_trace_markers(output, trace)


def compose_trace_response(trace) -> str:
    return format_trace_block(trace) or "[Agent Trace]\ntools: none"


def compose_current_information_unavailable_response() -> str:
    return "这个问题依赖当前比赛或新闻信息，但这次联网查询没有获得可靠结果，我现在无法核实。"
