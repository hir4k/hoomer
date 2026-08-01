"""User functions, native functions, and ``do`` blocks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hoomer import ast
from hoomer.errors import RuntimeHoomerError, SourceLocation
from hoomer.runtime.environment import Environment

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
        self.parameters = definition.parameters
        self.parameter_names = [parameter.name for parameter in self.parameters]
        self.is_fallible = self.name.endswith("!")

    @property
    def arity(self) -> int:
        return len(self.parameters)

    @property
    def positional_parameters(self) -> list[ast.FunctionParameterDefinition]:
        return [parameter for parameter in self.parameters if not parameter.is_named]

    @property
    def named_parameters(self) -> list[ast.FunctionParameterDefinition]:
        return [parameter for parameter in self.parameters if parameter.is_named]

    def accepts_arguments(
        self,
        positional_argument_count: int,
        named_argument_names: set[str],
    ) -> bool:
        positional_count_is_valid = (
            positional_argument_count == len(self.positional_parameters)
        )

        allowed_named_names = {parameter.name for parameter in self.named_parameters}
        required_named_names = {
            parameter.name
            for parameter in self.named_parameters
            if parameter.default_value is None
        }
        named_names_are_known = named_argument_names.issubset(allowed_named_names)
        required_names_are_present = required_named_names.issubset(named_argument_names)

        return (
            positional_count_is_valid
            and named_names_are_known
            and required_names_are_present
        )

    def call(
        self,
        interpreter: Interpreter,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> object:
        if not self.accepts_arguments(len(positional_arguments), set(named_arguments)):
            self._raise_argument_error(positional_arguments, named_arguments, location)

        call_environment = Environment(self.closure_environment)
        self._bind_positional_parameters(
            call_environment,
            positional_arguments,
            location,
        )
        self._bind_named_parameters(
            interpreter,
            call_environment,
            named_arguments,
            location,
        )

        return interpreter.execute_function_body(
            self.definition.body,
            call_environment,
        )

    def _bind_positional_parameters(
        self,
        call_environment: Environment,
        positional_arguments: list[object],
        location: SourceLocation,
    ) -> None:
        for parameter, parameter_value in zip(
            self.positional_parameters,
            positional_arguments,
            strict=True,
        ):
            call_environment.define(parameter.name, parameter_value, location=location)

    def _bind_named_parameters(
        self,
        interpreter: Interpreter,
        call_environment: Environment,
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> None:
        for parameter in self.named_parameters:
            if parameter.name in named_arguments:
                parameter_value = named_arguments[parameter.name]
            else:
                parameter_value = interpreter.evaluate_expression(
                    parameter.default_value,
                    call_environment,
                )
            call_environment.define(parameter.name, parameter_value, location=location)

    def _raise_argument_error(
        self,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> None:
        supplied_count = len(positional_arguments) + len(named_arguments)
        raise RuntimeHoomerError(
            location,
            f"Function `{self.name}` received arguments that do not match its parameters.",
            expected=self.signature,
            found=(
                f"{len(positional_arguments)} positional and "
                f"{len(named_arguments)} named argument(s) ({supplied_count} total)"
            ),
        )

    @property
    def signature(self) -> str:
        rendered_parameters: list[str] = []
        for parameter in self.parameters:
            rendered_name = parameter.name + (":" if parameter.is_named else "")
            if parameter.default_value is not None:
                rendered_name += " <default>"
            rendered_parameters.append(rendered_name)
        return f"{self.name}({', '.join(rendered_parameters)})"


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
