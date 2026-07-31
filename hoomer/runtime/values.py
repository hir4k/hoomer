"""Shared operations over Hoomer's dynamic runtime values."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hoomer.runtime.functions import FunctionGroup, NativeFunction, RuntimeBlock, RuntimeFunction
    from hoomer.runtime.modules import RuntimeModule
    from hoomer.runtime.reflection import ReflectionValue
    from hoomer.runtime.structs import RuntimeStructDefinition, RuntimeStructInstance


def runtime_type_name(value: object) -> str:
    """Return a Hoomer-facing type name rather than a Python implementation name."""

    from hoomer.runtime.functions import FunctionGroup, NativeFunction, RuntimeBlock, RuntimeFunction
    from hoomer.runtime.modules import RuntimeModule
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
    if isinstance(value, RuntimeModule):
        return "module"
    if isinstance(value, (RuntimeFunction, FunctionGroup, NativeFunction, RuntimeBlock)):
        return "function"
    if isinstance(value, ReflectionValue):
        return value.kind
    if isinstance(value, list):
        return "list"
    return type(value).__name__


def is_truthy(value: object) -> bool:
    """Only ``false`` and ``nil`` are falsey, keeping conditions predictable."""

    return value is not None and value is not False


def format_runtime_value(value: object, *, nested: bool = False) -> str:
    """Render a runtime value using Hoomer spellings.

    Strings print without quotes at the top level so ``print "Hello"`` produces
    ``Hello``. Nested strings keep quotes to make composite values unambiguous:
    ``User(name: "Hirak")`` is easier to read than ``User(name: Hirak)``.
    """

    from hoomer.runtime.functions import FunctionGroup, NativeFunction, RuntimeBlock, RuntimeFunction
    from hoomer.runtime.modules import RuntimeModule
    from hoomer.runtime.reflection import ReflectionValue
    from hoomer.runtime.structs import RuntimeStructDefinition, RuntimeStructInstance

    if value is None:
        return "nil"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return repr(value) if nested else value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        rendered_items = ", ".join(
            format_runtime_value(item, nested=True) for item in value
        )
        return f"[{rendered_items}]"
    if isinstance(value, RuntimeStructInstance):
        rendered_fields = ", ".join(
            f"{name}: {format_runtime_value(field_value, nested=True)}"
            for name, field_value in value.fields.items()
        )
        return f"{value.definition.name}({rendered_fields})"
    if isinstance(value, RuntimeStructDefinition):
        return f"struct {value.name}"
    if isinstance(value, RuntimeModule):
        return f"module {value.full_name}"
    if isinstance(value, ReflectionValue):
        rendered_fields = ", ".join(
            f"{name}: {format_runtime_value(field_value, nested=True)}"
            for name, field_value in value.fields.items()
        )
        return f"{value.kind}({rendered_fields})"
    if isinstance(value, (RuntimeFunction, FunctionGroup, NativeFunction)):
        return f"fn {value.name}"
    if isinstance(value, RuntimeBlock):
        return "do block"
    return str(value)

