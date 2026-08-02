"""User functions, built-in functions, and ``do`` blocks."""

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
        return [
            parameter
            for parameter in self.parameters
            if not parameter.is_named and not parameter.is_block
        ]

    @property
    def named_parameters(self) -> list[ast.FunctionParameterDefinition]:
        return [
            parameter
            for parameter in self.parameters
            if parameter.is_named and not parameter.is_block
        ]

    @property
    def block_parameter(self) -> ast.FunctionParameterDefinition | None:
        return next(
            (parameter for parameter in self.parameters if parameter.is_block),
            None,
        )

    def accepts_arguments(
        self,
        positional_argument_count: int,
        named_argument_names: set[str],
        has_block_argument: bool = False,
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
        block_presence_is_valid = has_block_argument == (self.block_parameter is not None)

        return (
            positional_count_is_valid
            and named_names_are_known
            and required_names_are_present
            and block_presence_is_valid
        )

    def call(
        self,
        interpreter: Interpreter,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> object:
        block_argument = None
        if positional_arguments and isinstance(positional_arguments[-1], SuppliedBlock):
            block_argument = positional_arguments[-1].value
            positional_arguments = positional_arguments[:-1]

        if not self.accepts_arguments(
            len(positional_arguments),
            set(named_arguments),
            block_argument is not None,
        ):
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

        if self.block_parameter is not None:
            call_environment.define(
                self.block_parameter.name,
                block_argument,
                location=location,
            )

        result = interpreter.execute_function_body(
            self.definition.body,
            call_environment,
            function_name=self.name,
            is_fallible=self.is_fallible,
        )
        return interpreter.finish_function_call(self, result, location)

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
            if parameter.is_block:
                rendered_name = "&" + parameter.name
            else:
                rendered_name = parameter.name + (":" if parameter.is_named else "")
            if parameter.default_value is not None:
                rendered_name += " <default>"
            rendered_parameters.append(rendered_name)
        return f"{self.name}({', '.join(rendered_parameters)})"


BuiltinImplementation = Callable[
    ["Interpreter", list[object], dict[str, object], SourceLocation],
    object,
]


@dataclass(slots=True)
class BuiltinFunction:
    name: str
    implementation: BuiltinImplementation
    parameter_names: list[str]
    is_fallible: bool = False

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
    """A parameterized closure created by a trailing ``do ... end`` block."""

    name = "<block>"
    parameter_names: list[str] = []
    arity = 0

    def __init__(self, expression: ast.BlockExpression, closure: Environment) -> None:
        self.expression = expression
        self.closure = closure
        self.parameter_names = expression.parameter_names
        self.arity = len(self.parameter_names)

    def call(
        self,
        interpreter: Interpreter,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> object:
        if named_arguments or len(positional_arguments) != self.arity:
            raise RuntimeHoomerError(
                location,
                "This `do` block received arguments that do not match its parameters.",
                expected=f"{self.arity} positional argument(s)",
                found=f"{len(positional_arguments) + len(named_arguments)} argument(s)",
            )
        call_environment = Environment(self.closure)
        for name, value in zip(
            self.parameter_names,
            positional_arguments,
            strict=True,
        ):
            call_environment.define(name, value, location=location)
        return interpreter.execute_function_body(
            self.expression.statements,
            call_environment,
            function_name="<block>",
            is_fallible=interpreter.current_function_is_fallible,
        )


@dataclass(frozen=True, slots=True)
class SuppliedBlock:
    """Keep the trailing block separate from ordinary positional arguments."""

    value: object
