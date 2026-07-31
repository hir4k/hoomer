"""User functions, native functions, overload groups, and ``do`` blocks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hoomer import ast
from hoomer.errors import RuntimeHoomerError, SourceLocation
from hoomer.runtime.environment import Environment
from hoomer.runtime.values import runtime_type_name

if TYPE_CHECKING:
    from hoomer.interpreter import Interpreter


class ReturnFromFunction(Exception):
    """Internal control-flow signal; Hoomer programs cannot catch or observe it."""

    def __init__(self, value: object) -> None:
        super().__init__()
        self.value = value


class RuntimeFunction:
    def __init__(
        self,
        definition: ast.FunctionDefinition,
        closure_environment: Environment,
    ) -> None:
        self.definition = definition
        self.closure_environment = closure_environment
        self.name = definition.name
        self.parameter_names = definition.parameter_names
        self.is_predicate = self.name.endswith("?")
        self.is_fallible = self.name.endswith("!")

    @property
    def arity(self) -> int:
        return len(self.parameter_names)

    def call(
        self,
        interpreter: Interpreter,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> object:
        argument_values = self._bind_arguments(
            positional_arguments,
            named_arguments,
            location,
        )
        call_environment = Environment(self.closure_environment)
        for parameter_name, argument_value in argument_values.items():
            call_environment.define(parameter_name, argument_value, location=location)

        returned_value = interpreter.execute_function_body(
            self.definition.body,
            call_environment,
        )

        if self.is_predicate and not isinstance(returned_value, bool):
            raise RuntimeHoomerError(
                location,
                f"Predicate function `{self.name}` returned "
                f"{runtime_type_name(returned_value)} instead of a boolean.",
                expected="`true` or `false`",
                found=runtime_type_name(returned_value),
            )

        return returned_value

    def _bind_arguments(
        self,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> dict[str, object]:
        too_many_positional_arguments = len(positional_arguments) > self.arity
        if too_many_positional_arguments:
            self._raise_argument_error(positional_arguments, named_arguments, location)

        bound_arguments = dict(zip(self.parameter_names, positional_arguments, strict=False))
        for argument_name, argument_value in named_arguments.items():
            name_is_unknown = argument_name not in self.parameter_names
            name_was_already_positional = argument_name in bound_arguments
            if name_is_unknown or name_was_already_positional:
                self._raise_argument_error(positional_arguments, named_arguments, location)
            bound_arguments[argument_name] = argument_value

        if len(bound_arguments) != self.arity:
            self._raise_argument_error(positional_arguments, named_arguments, location)

        return bound_arguments

    def _raise_argument_error(
        self,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> None:
        supplied_count = len(positional_arguments) + len(named_arguments)
        parameter_display = ", ".join(self.parameter_names)
        raise RuntimeHoomerError(
            location,
            f"Function `{self.name}` received arguments that do not match its parameters.",
            expected=f"{self.arity} argument(s): ({parameter_display})",
            found=f"{supplied_count} argument(s)",
        )


class FunctionGroup:
    """All definitions of one function name, selected by arity.

    Hoomer intentionally uses one easy-to-explain overloading rule. ``greet()``
    and ``greet(name)`` may coexist because their arities differ; two one-argument
    definitions may not. Named arguments still have to match the parameter names
    of the overload selected by its argument count.
    """

    def __init__(self, name: str, first_overload: RuntimeFunction) -> None:
        self.name = name
        self.overloads: list[RuntimeFunction] = [first_overload]

    def add_overload(self, function: RuntimeFunction, location: SourceLocation) -> None:
        arity_is_already_defined = any(
            overload.arity == function.arity for overload in self.overloads
        )
        if arity_is_already_defined:
            parameters = ", ".join(function.parameter_names)
            raise RuntimeHoomerError(
                location,
                f"Function `{self.name}` already has a {function.arity}-argument overload.",
                expected="an overload with a different number of parameters",
                found=f"`{self.name}({parameters})`",
            )
        self.overloads.append(function)

    def call(
        self,
        interpreter: Interpreter,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> object:
        supplied_count = len(positional_arguments) + len(named_arguments)
        eligible_overloads = [
            overload
            for overload in self.overloads
            if overload.arity == supplied_count
            and set(named_arguments).issubset(overload.parameter_names)
        ]

        if len(eligible_overloads) == 1:
            return eligible_overloads[0].call(
                interpreter,
                positional_arguments,
                named_arguments,
                location,
            )

        available_arities = ", ".join(str(overload.arity) for overload in self.overloads)
        raise RuntimeHoomerError(
            location,
            f"No overload of `{self.name}` matches these arguments.",
            expected=f"one of the available arities: {available_arities}",
            found=f"{supplied_count} argument(s)",
        )


NativeImplementation = Callable[
    ["Interpreter", list[object], dict[str, object], SourceLocation],
    object,
]


@dataclass(slots=True)
class NativeFunction:
    name: str
    implementation: NativeImplementation
    parameter_names: list[str]

    @property
    def arity(self) -> int:
        return len(self.parameter_names)

    def call(
        self,
        interpreter: Interpreter,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> object:
        return self.implementation(
            interpreter,
            positional_arguments,
            named_arguments,
            location,
        )


class RuntimeBlock:
    """A zero-parameter closure created by a trailing ``do ... end`` block."""

    name = "<block>"
    parameter_names: list[str] = []
    arity = 0

    def __init__(self, expression: ast.BlockExpression, closure: Environment) -> None:
        self.expression = expression
        self.closure = closure

    def call(
        self,
        interpreter: Interpreter,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> object:
        if positional_arguments or named_arguments:
            raise RuntimeHoomerError(
                location,
                "This `do` block does not accept arguments.",
                expected="no arguments",
                found=f"{len(positional_arguments) + len(named_arguments)} argument(s)",
            )
        return interpreter.execute_function_body(
            self.expression.statements,
            Environment(self.closure),
        )
