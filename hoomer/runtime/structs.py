"""Runtime representations for struct definitions and instances."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hoomer import ast
from hoomer.errors import RuntimeHoomerError, SourceLocation
from hoomer.runtime.environment import Environment

if TYPE_CHECKING:
    from hoomer.interpreter import Interpreter


@dataclass(frozen=True, slots=True)
class RuntimeFieldDefinition:
    name: str
    default_expression: ast.Expression | None


@dataclass(frozen=True, slots=True)
class ErrorTraceFrame:
    function_name: str
    location: SourceLocation


class RuntimeStructDefinition:
    """A callable struct schema with unevaluated field defaults.

    Defaults remain expressions until construction. This matters once Hoomer
    gains mutable composite values: evaluating a default once at definition time
    would accidentally share the same value between every instance. For example,
    a future ``items: []`` default must create a fresh list per struct instance.
    """

    def __init__(
        self,
        name: str,
        fields: list[RuntimeFieldDefinition],
        definition_environment: Environment,
        *,
        is_error: bool = False,
    ) -> None:
        self.name = name
        self.fields = fields
        self.definition_environment = definition_environment
        self.is_error = is_error

    def call(
        self,
        interpreter: Interpreter,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> RuntimeStructInstance:
        declaration_kind = "Error" if self.is_error else "Struct"
        if positional_arguments:
            raise RuntimeHoomerError(
                location,
                f"{declaration_kind} `{self.name}` is constructed with named fields.",
                expected=f"`{self.name}(field_name: value)`",
                found=f"{len(positional_arguments)} positional argument(s)",
            )

        known_field_names = {field.name for field in self.fields}
        unknown_field_names = set(named_arguments) - known_field_names
        if unknown_field_names:
            unknown_name = sorted(unknown_field_names)[0]
            raise RuntimeHoomerError(
                location,
                f"{declaration_kind} `{self.name}` has no field named `{unknown_name}`.",
                expected="one of: " + ", ".join(sorted(known_field_names)),
                found=unknown_name,
            )

        instance_fields: OrderedDict[str, object] = OrderedDict()
        missing_required_fields = [
            field.name
            for field in self.fields
            if field.default_expression is None and field.name not in named_arguments
        ]
        if missing_required_fields:
            raise RuntimeHoomerError(
                location,
                f"{declaration_kind} `{self.name}` is missing required fields.",
                expected="named values for: " + ", ".join(missing_required_fields),
                found="no value for: " + ", ".join(missing_required_fields),
            )

        for field_definition in self.fields:
            if field_definition.name in named_arguments:
                field_value = named_arguments[field_definition.name]
            else:
                field_value = interpreter.evaluate_expression(
                    field_definition.default_expression,
                    self.definition_environment,
                )
            instance_fields[field_definition.name] = field_value

        trace = []
        if self.is_error:
            trace.append(
                ErrorTraceFrame(
                    interpreter.current_function_name,
                    location,
                )
            )
        return RuntimeStructInstance(self, instance_fields, trace)


@dataclass(slots=True, eq=False)
class RuntimeStructInstance:
    definition: RuntimeStructDefinition
    fields: OrderedDict[str, object]
    error_trace: list[ErrorTraceFrame]

    def get_field(self, field_name: str, location: SourceLocation) -> object:
        if field_name in self.fields:
            return self.fields[field_name]

        raise RuntimeHoomerError(
            location,
            f"Struct `{self.definition.name}` has no field named `{field_name}`.",
            expected="one of: " + ", ".join(self.fields),
            found=field_name,
        )

    def set_field(self, field_name: str, value: object, location: SourceLocation) -> object:
        if field_name not in self.fields:
            raise RuntimeHoomerError(
                location,
                f"Struct `{self.definition.name}` has no field named `{field_name}`.",
                expected="one of: " + ", ".join(self.fields),
                found=field_name,
            )

        self.fields[field_name] = value
        return value

    @property
    def is_error(self) -> bool:
        return self.definition.is_error

    def add_error_frame(self, function_name: str, location: SourceLocation) -> None:
        if not self.is_error:
            return
        frame = ErrorTraceFrame(function_name, location)
        if self.error_trace and self.error_trace[-1] == frame:
            return
        self.error_trace.append(frame)


def is_error_value(value: object) -> bool:
    return isinstance(value, RuntimeStructInstance) and value.is_error
