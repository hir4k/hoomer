"""Runtime metadata exposed through Hoomer's built-in ``reflection`` function."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from hoomer.errors import RuntimeHoomerError, SourceLocation
from hoomer.runtime.functions import BuiltinFunction, RuntimeBlock, RuntimeFunction
from hoomer.runtime.packages import RuntimePackage
from hoomer.runtime.structs import RuntimeStructDefinition, RuntimeStructInstance
from hoomer.runtime.values import runtime_type_name
from hoomer.runtime.types import type_of
from hoomer.runtime.types import RuntimeType


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
                    ("values", _field_values(value)),
                    ("is_error", value.is_error),
                    ("type", value.definition),
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
                    ("is_error", value.is_error),
                    ("type", value),
                ]
            ),
        )

    if isinstance(value, RuntimeType):
        return ReflectionValue(
            "TypeInfo",
            OrderedDict(
                [
                    ("name", value.name),
                    ("kind", "primitive"),
                ]
            ),
        )

    if isinstance(value, RuntimeFunction):
        return _reflect_function(value)

    if isinstance(value, BuiltinFunction):
        return ReflectionValue(
            "FunctionInfo",
            OrderedDict([("name", value.name), ("parameters", value.parameter_names)]),
        )

    if isinstance(value, RuntimeBlock):
        return ReflectionValue(
            "FunctionInfo",
            OrderedDict(
                [
                    ("name", value.name),
                    ("parameters", value.parameter_names),
                    ("is_fallible", False),
                ]
            ),
        )

    if isinstance(value, RuntimePackage):
        package_values = [
            (name, value.environment.get_local(name))
            for name in sorted(value.public_member_names)
        ]
        function_names = [
            name
            for name, member in package_values
            if isinstance(member, (RuntimeFunction, BuiltinFunction))
        ]
        struct_names = [
            name
            for name, member in package_values
            if isinstance(member, RuntimeStructDefinition) and not member.is_error
        ]
        error_names = [
            name
            for name, member in package_values
            if isinstance(member, RuntimeStructDefinition) and member.is_error
        ]
        constant_names = [
            name
            for name, member in package_values
            if name.isupper()
        ]
        return ReflectionValue(
            "PackageInfo",
            OrderedDict(
                [
                    ("name", value.name),
                    ("path", value.import_path),
                    ("functions", function_names),
                    ("structs", struct_names),
                    ("errors", error_names),
                    ("constants", constant_names),
                    ("members", sorted(value.public_member_names)),
                ]
            ),
        )

    return ReflectionValue(
        "ValueInfo",
        OrderedDict(
            [
                ("name", runtime_type_name(value)),
                ("fields", []),
                ("type", type_of(value)),
            ]
        ),
    )


def _reflect_function(function: RuntimeFunction) -> ReflectionValue:
    return ReflectionValue(
        "FunctionInfo",
        OrderedDict(
            [
                ("name", function.name),
                ("parameters", function.parameter_names),
                ("is_fallible", function.is_fallible),
            ]
        ),
    )


def _field_values(value: RuntimeStructInstance) -> RuntimeMap:
    from hoomer.runtime.maps import RuntimeMap

    field_values = RuntimeMap()
    internal_location = SourceLocation("<reflection>", 1, 1)
    for field_name, field_value in value.fields.items():
        field_values.set(field_name, field_value, internal_location)
    return field_values
