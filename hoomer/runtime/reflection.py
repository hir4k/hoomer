"""Basic reflection values exposed through Hoomer's built-in ``reflect``."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from hoomer.errors import RuntimeHoomerError, SourceLocation
from hoomer.runtime.functions import FunctionGroup, NativeFunction, RuntimeFunction
from hoomer.runtime.modules import RuntimeModule
from hoomer.runtime.structs import RuntimeStructDefinition, RuntimeStructInstance
from hoomer.runtime.values import runtime_type_name


@dataclass(slots=True)
class ReflectionValue:
    kind: str
    fields: OrderedDict[str, object]

    def get_field(self, field_name: str, location: SourceLocation) -> object:
        if field_name in self.fields:
            return self.fields[field_name]

        raise RuntimeHoomerError(
            location,
            f"Reflection value `{self.kind}` has no field named `{field_name}`.",
            expected="one of: " + ", ".join(self.fields),
            found=field_name,
        )


def reflect_runtime_value(value: object) -> ReflectionValue:
    if isinstance(value, RuntimeStructInstance):
        return ReflectionValue(
            "StructInfo",
            OrderedDict(
                [
                    ("name", value.definition.name),
                    ("fields", list(value.fields)),
                ]
            ),
        )

    if isinstance(value, RuntimeStructDefinition):
        return ReflectionValue(
            "StructInfo",
            OrderedDict(
                [
                    ("name", value.name),
                    ("fields", [field.name for field in value.fields]),
                ]
            ),
        )

    if isinstance(value, RuntimeFunction):
        return _reflect_function(value)

    if isinstance(value, NativeFunction):
        return ReflectionValue(
            "FunctionInfo",
            OrderedDict([("name", value.name), ("parameters", value.parameter_names)]),
        )

    if isinstance(value, FunctionGroup):
        parameter_lists = [overload.parameter_names for overload in value.overloads]
        return ReflectionValue(
            "FunctionInfo",
            OrderedDict([("name", value.name), ("parameters", parameter_lists)]),
        )

    if isinstance(value, RuntimeModule):
        module_values = [
            (name, value.environment.get_local(name))
            for name in sorted(value.public_member_names)
        ]
        function_names = [
            name
            for name, member in module_values
            if isinstance(member, (RuntimeFunction, FunctionGroup, NativeFunction))
        ]
        struct_names = [
            name
            for name, member in module_values
            if isinstance(member, RuntimeStructDefinition)
        ]
        return ReflectionValue(
            "ModuleInfo",
            OrderedDict([("functions", function_names), ("structs", struct_names)]),
        )

    return ReflectionValue(
        "ValueInfo",
        OrderedDict([("name", runtime_type_name(value)), ("fields", [])]),
    )


def _reflect_function(function: RuntimeFunction) -> ReflectionValue:
    return ReflectionValue(
        "FunctionInfo",
        OrderedDict(
            [
                ("name", function.name),
                ("parameters", function.parameter_names),
            ]
        ),
    )
