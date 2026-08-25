import json
from typing import Callable, Dict, List, Set


def tool_call_from_planned(index: int, planned) -> dict:
    return {
        "id": "planned-{0}-{1}".format(str(planned.name).replace("_", "-"), index),
        "type": "function",
        "function": {
            "name": planned.name,
            "arguments": json.dumps(planned.arguments or {}, ensure_ascii=False),
        },
    }


def available_planned_calls(plan, disabled_tools=None, is_tool_available: Callable[[str], bool] = None) -> list:
    disabled: Set[str] = set(disabled_tools or set())
    available = is_tool_available or (lambda _name: True)
    result = []
    for planned in plan.required_tools:
        if planned.name in disabled:
            continue
        if not available(planned.name):
            continue
        result.append(planned)
    return result


def initial_tool_calls_from_plan(plan, disabled_tools=None, is_tool_available: Callable[[str], bool] = None) -> List[dict]:
    calls = []
    for planned in available_planned_calls(plan, disabled_tools, is_tool_available):
        calls.append(tool_call_from_planned(len(calls) + 1, planned))
    return calls


def initial_tool_dependencies_from_plan(plan, calls: List[dict]) -> Dict[str, List[str]]:
    ids_by_name: Dict[str, List[str]] = {}
    for call in calls:
        function = (call or {}).get("function") or {}
        name = str(function.get("name") or "")
        if not name:
            continue
        ids_by_name.setdefault(name, []).append(str(call.get("id") or ""))

    result: Dict[str, List[str]] = {}
    for tool_name, dependency_names in dict(getattr(plan, "dependencies", {}) or {}).items():
        target_ids = ids_by_name.get(str(tool_name), [])
        if not target_ids:
            continue
        dependency_ids = []
        for dependency_name in list(dependency_names or []):
            dependency_ids.extend([
                item for item in ids_by_name.get(str(dependency_name), []) if item
            ])
        if not dependency_ids:
            continue
        for target_id in target_ids:
            if target_id:
                result[target_id] = list(dependency_ids)
    return result


def should_execute_initial_plan(plan, disabled_tools=None, is_tool_available: Callable[[str], bool] = None) -> bool:
    available_required = available_planned_calls(plan, disabled_tools, is_tool_available)
    if len(available_required) > 1:
        return True
    if len(available_required) == 1:
        return bool(
            plan.constraints.get("direct_trace_response")
            or plan.constraints.get("execute_single_required_tool")
        )
    return False
