import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional, Set, Union


PermissionLevel = Literal["safe_read", "safe_write", "confirm_write", "admin_action"]
ToolHandler = Callable[..., Union[Awaitable[str], str]]
JSON_SCHEMA_TYPES = {"object", "array", "string", "integer", "number", "boolean", "null"}


class ToolArgumentError(ValueError):
    pass


class ToolSchemaError(ValueError):
    pass


@dataclass
class ToolSpec:
    # Single source of truth for a callable agent tool: schema shown to the
    # model, handler invoked by executor.py, and permission level enforced
    # server-side before any handler can run.
    name: str
    description: str
    parameters: Dict[str, Any]
    handler: ToolHandler
    permission: PermissionLevel = "safe_read"
    enabled: bool = True
    category: str = "general"
    timeout_seconds: float = 20.0
    parallel_safe: bool = False
    idempotent: bool = False
    result_contains_untrusted_content: bool = True


_TOOL_REGISTRY: Dict[str, ToolSpec] = {}


def clear_registry() -> None:
    _TOOL_REGISTRY.clear()


def register_tool(spec: ToolSpec) -> ToolSpec:
    # Duplicate names would make the LLM call surface ambiguous, so fail fast
    # during registration instead of shadowing an existing tool.
    if spec.name in _TOOL_REGISTRY:
        raise ValueError("Duplicate tool: {0}".format(spec.name))
    try:
        validate_tool_schema(spec.parameters)
    except ToolSchemaError as exc:
        raise ValueError("Invalid schema for tool {0}: {1}".format(spec.name, exc)) from exc
    spec.parameters = normalize_tool_schema(spec.parameters)
    _TOOL_REGISTRY[spec.name] = spec
    return spec


def ensure_tool(spec: ToolSpec) -> ToolSpec:
    existing = _TOOL_REGISTRY.get(spec.name)
    if existing is not None:
        return existing
    return register_tool(spec)


def get_tool(name: str) -> Optional[ToolSpec]:
    return _TOOL_REGISTRY.get(name)


def list_enabled_tools(include_permissions: Optional[Set[str]] = None, exclude_names: Optional[Set[str]] = None) -> List[ToolSpec]:
    tools = [tool for tool in _TOOL_REGISTRY.values() if tool.enabled]
    if include_permissions is not None:
        tools = [tool for tool in tools if tool.permission in include_permissions]
    if exclude_names is not None:
        tools = [tool for tool in tools if tool.name not in exclude_names]
    return tools


def build_openai_tools(include_permissions: Optional[Set[str]] = None, exclude_names: Optional[Set[str]] = None) -> List[dict]:
    # Only schema metadata is sent to the model. Permission enforcement stays
    # server-side in executor.py and cannot be bypassed by tool_choice output.
    result = []
    for spec in list_enabled_tools(include_permissions, exclude_names=exclude_names):
        result.append({
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        })
    return result


def validate_tool_schema(schema: Any) -> None:
    if not isinstance(schema, dict):
        raise ToolSchemaError("parameters must be an object schema")
    root_types = _schema_types(schema)
    if root_types and root_types != ["object"]:
        raise ToolSchemaError("parameters root type must be object")
    if not root_types and "properties" not in schema:
        raise ToolSchemaError("parameters root type must be object")
    _validate_schema_node(schema, path="parameters")


def normalize_tool_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    normalized = _normalize_schema_node(schema)
    return normalized if isinstance(normalized, dict) else schema


def _normalize_schema_node(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    normalized: Dict[str, Any] = {}
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            normalized[key] = {
                prop_name: _normalize_schema_node(prop_schema)
                for prop_name, prop_schema in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            normalized[key] = _normalize_schema_node(value)
        elif key == "additionalProperties" and isinstance(value, dict):
            normalized[key] = _normalize_schema_node(value)
        else:
            normalized[key] = value

    if _schema_types(normalized) == ["object"] and "additionalProperties" not in normalized:
        normalized["additionalProperties"] = False
    return normalized


def _validate_schema_type(schema: Dict[str, Any], path: str) -> None:
    schema_type = schema.get("type")
    if schema_type is None:
        return
    if isinstance(schema_type, str):
        types = [schema_type]
    elif isinstance(schema_type, list) and all(isinstance(item, str) for item in schema_type):
        types = list(schema_type)
    else:
        raise ToolSchemaError("{0}.type must be a string or list of strings".format(path))
    invalid = [item for item in types if item not in JSON_SCHEMA_TYPES]
    if invalid:
        raise ToolSchemaError("{0}.type contains unsupported value {1}".format(path, invalid[0]))


def _validate_schema_node(schema: Any, path: str) -> None:
    if not isinstance(schema, dict):
        raise ToolSchemaError("{0} must be an object".format(path))
    _validate_schema_type(schema, path)
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise ToolSchemaError("{0}.properties must be an object".format(path))
        for key, child_schema in properties.items():
            if not isinstance(key, str):
                raise ToolSchemaError("{0}.properties keys must be strings".format(path))
            _validate_schema_node(child_schema, "{0}.properties.{1}".format(path, key))
    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ToolSchemaError("{0}.required must be a list of strings".format(path))
    additional = schema.get("additionalProperties", True)
    if not (additional is True or additional is False or isinstance(additional, dict)):
        raise ToolSchemaError("{0}.additionalProperties must be boolean or object".format(path))
    if isinstance(additional, dict):
        _validate_schema_node(additional, "{0}.additionalProperties".format(path))
    items = schema.get("items")
    if items is not None and not isinstance(items, dict):
        raise ToolSchemaError("{0}.items must be an object".format(path))
    if isinstance(items, dict):
        _validate_schema_node(items, "{0}.items".format(path))
    for keyword in ("minLength", "maxLength", "minItems", "maxItems"):
        if keyword in schema and not isinstance(schema.get(keyword), int):
            raise ToolSchemaError("{0}.{1} must be an integer".format(path, keyword))
    for keyword in ("minimum", "maximum"):
        if keyword in schema and not isinstance(schema.get(keyword), (int, float)):
            raise ToolSchemaError("{0}.{1} must be a number".format(path, keyword))
    enum_values = schema.get("enum")
    if enum_values is not None and not isinstance(enum_values, list):
        raise ToolSchemaError("{0}.enum must be a list".format(path))


def parse_and_validate_arguments(spec: ToolSpec, raw_arguments: Any) -> Dict[str, Any]:
    if isinstance(raw_arguments, dict):
        value = raw_arguments
    else:
        try:
            value = json.loads(str(raw_arguments or "{}"))
        except json.JSONDecodeError as exc:
            raise ToolArgumentError("invalid JSON") from exc

    if not isinstance(value, dict):
        raise ToolArgumentError("tool arguments must be an object")

    errors: List[str] = []
    _validate_json_schema_value(
        value,
        spec.parameters or {"type": "object", "properties": {}},
        path="arguments",
        errors=errors,
    )
    if errors:
        raise ToolArgumentError("; ".join(errors[:3]))
    return value


def _schema_types(schema: Dict[str, Any]) -> List[str]:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        return [str(item) for item in schema_type]
    if isinstance(schema_type, str):
        return [schema_type]
    if "properties" in schema or "required" in schema:
        return ["object"]
    return []


def _type_matches(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _type_label(types: List[str]) -> str:
    return " or ".join(types)


def _validate_json_schema_value(value: Any, schema: Any, path: str, errors: List[str]) -> None:
    if not isinstance(schema, dict):
        return

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        errors.append("{0} must be one of {1}".format(path, ", ".join([repr(item) for item in enum_values])))
        return

    expected_types = _schema_types(schema)
    if expected_types and not any(_type_matches(value, item) for item in expected_types):
        errors.append("{0} must be {1}".format(path, _type_label(expected_types)))
        return

    if isinstance(value, dict):
        _validate_object(value, schema, path, errors)
    elif isinstance(value, list):
        _validate_array(value, schema, path, errors)
    elif isinstance(value, str):
        _validate_string(value, schema, path, errors)
    elif isinstance(value, int) or isinstance(value, float):
        if not isinstance(value, bool):
            _validate_number(value, schema, path, errors)


def _validate_object(value: Dict[str, Any], schema: Dict[str, Any], path: str, errors: List[str]) -> None:
    properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    for key in required:
        if key not in value:
            errors.append("{0}.{1} is required".format(path, key))

    additional = schema.get("additionalProperties", True)
    for key, item in value.items():
        child_path = "{0}.{1}".format(path, key)
        if key in properties:
            _validate_json_schema_value(item, properties[key], child_path, errors)
        elif additional is False:
            errors.append("{0} is not allowed".format(child_path))
        elif isinstance(additional, dict):
            _validate_json_schema_value(item, additional, child_path, errors)


def _validate_array(value: List[Any], schema: Dict[str, Any], path: str, errors: List[str]) -> None:
    min_items = schema.get("minItems")
    max_items = schema.get("maxItems")
    if isinstance(min_items, int) and len(value) < min_items:
        errors.append("{0} must contain at least {1} items".format(path, min_items))
    if isinstance(max_items, int) and len(value) > max_items:
        errors.append("{0} must contain at most {1} items".format(path, max_items))
    item_schema = schema.get("items")
    if isinstance(item_schema, dict):
        for index, item in enumerate(value):
            _validate_json_schema_value(item, item_schema, "{0}[{1}]".format(path, index), errors)


def _validate_string(value: str, schema: Dict[str, Any], path: str, errors: List[str]) -> None:
    min_length = schema.get("minLength")
    max_length = schema.get("maxLength")
    if isinstance(min_length, int) and len(value) < min_length:
        errors.append("{0} must contain at least {1} characters".format(path, min_length))
    if isinstance(max_length, int) and len(value) > max_length:
        errors.append("{0} must contain at most {1} characters".format(path, max_length))


def _validate_number(value: Union[int, float], schema: Dict[str, Any], path: str, errors: List[str]) -> None:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if isinstance(minimum, (int, float)) and value < minimum:
        errors.append("{0} must be >= {1}".format(path, minimum))
    if isinstance(maximum, (int, float)) and value > maximum:
        errors.append("{0} must be <= {1}".format(path, maximum))
