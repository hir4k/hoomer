"""Shared operations over Hoomer's dynamic runtime values."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hoomer.runtime.functions import NativeFunction, RuntimeBlock, RuntimeFunction
    from hoomer.runtime.maps import RuntimeMap
    from hoomer.runtime.packages import RuntimePackage
    from hoomer.runtime.reflection import ReflectionValue
    from hoomer.runtime.structs import RuntimeStructDefinition, RuntimeStructInstance


def runtime_type_name(value: object) -> str:
    """Return a Hoomer-facing type name rather than a Python implementation name."""

    from hoomer.runtime.functions import NativeFunction, RuntimeBlock, RuntimeFunction
    from hoomer.runtime.maps import RuntimeMap
    from hoomer.runtime.packages import RuntimePackage
    from hoomer.runtime.reflection import ReflectionValue
    from hoomer.runtime.structs import RuntimeStructDefinition, RuntimeStructInstance

    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, RuntimeStructInstance):
        return value.definition.name
    if isinstance(value, RuntimeStructDefinition):
        return "struct"
    if isinstance(value, RuntimePackage):
        return "package"
    if isinstance(value, (RuntimeFunction, NativeFunction, RuntimeBlock)):
        return "function"
    if isinstance(value, ReflectionValue):
        return value.kind
    if isinstance(value, list):
        return "list"
    if isinstance(value, RuntimeMap):
        return "map"
    if isinstance(value, range):
        return "range"
    return type(value).__name__


def format_runtime_value(value: object, *, nested: bool = False) -> str:
    """Render a runtime value using Hoomer spellings.

    Strings print without quotes at the top level so ``print "Hello"`` produces
    ``Hello``. Nested strings keep quotes to make composite values unambiguous:
    ``User(name: "Hirak")`` is easier to read than ``User(name: Hirak)``.
    """

    from hoomer.runtime.functions import NativeFunction, RuntimeBlock, RuntimeFunction
    from hoomer.runtime.maps import RuntimeMap
    from hoomer.runtime.packages import RuntimePackage
    from hoomer.runtime.reflection import ReflectionValue
    from hoomer.runtime.structs import RuntimeStructDefinition, RuntimeStructInstance

    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _quote_string(value) if nested else value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        rendered_items = ", ".join(
            format_runtime_value(item, nested=True) for item in value
        )
        return f"[{rendered_items}]"
    if isinstance(value, RuntimeMap):
        rendered_entries = ", ".join(
            f"{format_runtime_value(key, nested=True)}: "
            f"{format_runtime_value(entry_value, nested=True)}"
            for key, entry_value in value.items()
        )
        return "{" + rendered_entries + "}"
    if isinstance(value, range):
        last_value = value.stop - value.step
        return f"{value.start}..{last_value}"
    if isinstance(value, RuntimeStructInstance):
        rendered_fields = ", ".join(
            f"{name}: {format_runtime_value(field_value, nested=True)}"
            for name, field_value in value.fields.items()
        )
        return f"{value.definition.name}({rendered_fields})"
    if isinstance(value, RuntimeStructDefinition):
        return f"struct {value.name}"
    if isinstance(value, RuntimePackage):
        return f"package {value.name} ({value.import_path})"
    if isinstance(value, ReflectionValue):
        rendered_fields = ", ".join(
            f"{name}: {format_runtime_value(field_value, nested=True)}"
            for name, field_value in value.fields.items()
        )
        return f"{value.kind}({rendered_fields})"
    if isinstance(value, (RuntimeFunction, NativeFunction)):
        return f"fn {value.name}"
    if isinstance(value, RuntimeBlock):
        return "do block"
    return str(value)


def _quote_string(value: str) -> str:
    """Render a nested string using Hoomer's supported escape sequences."""

    escaped_value = value.replace("\\", "\\\\")
    escaped_value = escaped_value.replace('"', '\\"')
    escaped_value = escaped_value.replace("\n", "\\n")
    escaped_value = escaped_value.replace("\r", "\\r")
    escaped_value = escaped_value.replace("\t", "\\t")
    return f'"{escaped_value}"'
