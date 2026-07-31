"""Tree-walking evaluation for parsed Hoomer programs."""

from __future__ import annotations

import io
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from hoomer import ast
from hoomer.errors import HoomerError, RuntimeHoomerError, SourceLocation
from hoomer.lexer import Lexer
from hoomer.parser import Parser
from hoomer.runtime.environment import Environment
from hoomer.runtime.functions import (
    FunctionGroup,
    NativeFunction,
    ReturnFromFunction,
    RuntimeBlock,
    RuntimeFunction,
)
from hoomer.runtime.modules import ModuleRegistry, RuntimeModule
from hoomer.runtime.reflection import ReflectionValue, reflect_runtime_value
from hoomer.runtime.structs import (
    RuntimeFieldDefinition,
    RuntimeStructDefinition,
    RuntimeStructInstance,
)
from hoomer.runtime.values import format_runtime_value, is_truthy, runtime_type_name


class ContinueLoop(Exception):
    """Internal control-flow signal consumed by the nearest running loop."""


class Interpreter:
    """Own runtime state and evaluate Hoomer AST nodes.

    One interpreter instance is one Hoomer process. Its global environment,
    module registry, and import cache intentionally survive multiple
    ``execute_source`` calls; that is what lets the REPL remember earlier lines
    and imported files refer to modules loaded earlier in the process.
    """

    def __init__(
        self,
        *,
        output: TextIO | None = None,
        module_search_paths: Iterable[str | Path] | None = None,
    ) -> None:
        self.output = output or sys.stdout
        self.global_environment = Environment()
        self.module_registry = ModuleRegistry(self.global_environment)
        self.module_search_paths = [
            Path(search_path).resolve()
            for search_path in (module_search_paths or [Path.cwd()])
        ]
        self._files_being_loaded: set[Path] = set()
        self._loaded_files: set[Path] = set()
        self._function_call_depth = 0
        self._loop_depth = 0
        self._install_builtins()

    @classmethod
    def capture_output(
        cls,
        *,
        module_search_paths: Iterable[str | Path] | None = None,
    ) -> tuple[Interpreter, io.StringIO]:
        """Convenience constructor for tests and embedding applications."""

        output_buffer = io.StringIO()
        return (
            cls(output=output_buffer, module_search_paths=module_search_paths),
            output_buffer,
        )

    def execute_source(self, source_code: str, file_name: str = "<source>") -> object:
        program = self._parse_source(source_code, file_name)
        return self.execute_program(program)

    def execute_file(self, file_path: str | Path) -> object:
        resolved_path = Path(file_path).resolve()
        source_program = self._parse_file(resolved_path)
        return self._execute_program_from_file(source_program, resolved_path)

    @staticmethod
    def _parse_source(source_code: str, file_name: str) -> ast.Program:
        tokens = Lexer(source_code, file_name).scan_tokens()
        return Parser(tokens).parse()

    def _parse_file(self, resolved_path: Path) -> ast.Program:
        source_code = resolved_path.read_text(encoding="utf-8")
        return self._parse_source(source_code, str(resolved_path))

    def _execute_program_from_file(
        self,
        source_program: ast.Program,
        resolved_path: Path,
    ) -> object:
        original_search_paths = list(self.module_search_paths)

        # Imports are normally written relative to the source file being run.
        # Temporarily checking its directory first makes ``hoomer run app/main.hmr``
        # behave the same regardless of the shell's current working directory.
        source_directory = resolved_path.parent
        if source_directory not in self.module_search_paths:
            self.module_search_paths.insert(0, source_directory)

        try:
            result = self.execute_program(source_program)
            self._loaded_files.add(resolved_path)
            return result
        finally:
            self.module_search_paths = original_search_paths

    def execute_program(self, program: ast.Program) -> object:
        try:
            return self.execute_statements(program.statements, self.global_environment)
        except ReturnFromFunction as return_signal:
            # The parser accepts ``return`` wherever a statement may occur so it
            # can stay context-free. The runtime has the information needed to
            # explain the actual mistake: there is no active function call.
            raise RuntimeHoomerError(
                SourceLocation("<runtime>", 1, 1),
                "`return` can only be used while a function or `do` block is running.",
                expected="`return` inside `fn ... end` or `do ... end`",
                found=format_runtime_value(return_signal.value),
            ) from None

    def execute_function_body(
        self,
        statements: list[ast.Statement],
        environment: Environment,
    ) -> object:
        enclosing_loop_depth = self._loop_depth
        self._function_call_depth += 1
        # A loop inside the caller is not a loop inside the called function.
        # Resetting the depth prevents ``continue`` in a helper from silently
        # continuing its caller's loop; loops created by the function increment
        # this fresh depth normally.
        self._loop_depth = 0
        try:
            try:
                return self.execute_statements(statements, environment)
            except ReturnFromFunction as return_signal:
                return return_signal.value
        finally:
            self._loop_depth = enclosing_loop_depth
            self._function_call_depth -= 1

    def execute_statements(
        self,
        statements: list[ast.Statement],
        environment: Environment,
        active_module: RuntimeModule | None = None,
    ) -> object:
        last_value: object = None
        for statement in statements:
            last_value = self.execute_statement(statement, environment, active_module)
        return last_value

    def execute_statement(
        self,
        statement: ast.Statement,
        environment: Environment,
        active_module: RuntimeModule | None = None,
    ) -> object:
        if isinstance(statement, ast.ExpressionStatement):
            expression_value = self.evaluate_expression(statement.expression, environment)
            if active_module is not None:
                assignment_expression = statement.expression
                if isinstance(assignment_expression, ast.AssignmentExpression):
                    assignment_target = assignment_expression.target
                    if isinstance(assignment_target, ast.VariableExpression):
                        # Constants are the one module declaration without a
                        # separate ``pub`` form. Their UPPER_SNAKE_CASE name is
                        # already explicit, so declaring one makes it available
                        # as ``Module.CONSTANT_NAME`` automatically.
                        active_module.make_public(assignment_target.name)
            return expression_value

        if isinstance(statement, ast.PrintStatement):
            value = self.evaluate_expression(statement.expression, environment)
            print(format_runtime_value(value), file=self.output)
            return None

        if isinstance(statement, ast.ReturnStatement):
            return_value = (
                None
                if statement.expression is None
                else self.evaluate_expression(statement.expression, environment)
            )
            if self._function_call_depth == 0:
                raise RuntimeHoomerError(
                    statement.location,
                    "`return` cannot be used at the top level.",
                    expected="`return` inside a function or `do` block",
                    found="top-level `return`",
                )
            raise ReturnFromFunction(return_value)

        if isinstance(statement, ast.FunctionDefinition):
            return self._define_function(statement, environment, active_module)

        if isinstance(statement, ast.StructDefinition):
            return self._define_struct(statement, environment, active_module)

        if isinstance(statement, ast.ModuleDefinition):
            return self._execute_module_definition(statement)

        if isinstance(statement, ast.ImportStatement):
            return self._execute_import(statement, environment)

        if isinstance(statement, ast.IfStatement):
            return self._execute_if(statement, environment, active_module)

        if isinstance(statement, ast.WhenStatement):
            return self._execute_when(statement, environment, active_module)

        if isinstance(statement, ast.ForStatement):
            return self._execute_for(statement, environment, active_module)

        if isinstance(statement, ast.ContinueStatement):
            if self._loop_depth == 0:
                raise RuntimeHoomerError(
                    statement.location,
                    "`continue` can only be used inside a `for` loop.",
                    expected="`continue` between `for ... in ...` and its `end`",
                    found="`continue` outside a loop",
                )
            raise ContinueLoop()

        raise RuntimeHoomerError(
            statement.location,
            f"The interpreter does not know how to execute {type(statement).__name__}.",
        )

    def evaluate_expression(
        self,
        expression: ast.Expression,
        environment: Environment,
    ) -> object:
        if isinstance(expression, ast.LiteralExpression):
            if isinstance(expression.value, str):
                return self._interpolate_string(expression.value, expression.location, environment)
            return expression.value

        if isinstance(expression, ast.VariableExpression):
            return environment.get(expression.name, expression.location)

        if isinstance(expression, ast.UnaryExpression):
            return self._evaluate_unary(expression, environment)

        if isinstance(expression, ast.BinaryExpression):
            return self._evaluate_binary(expression, environment)

        if isinstance(expression, ast.AssignmentExpression):
            return self._evaluate_assignment(expression, environment)

        if isinstance(expression, ast.CallExpression):
            return self._evaluate_call(expression, environment)

        if isinstance(expression, ast.FieldAccessExpression):
            target_value = self.evaluate_expression(expression.target, environment)
            return self._read_field(target_value, expression.field_name, expression.location)

        if isinstance(expression, ast.BlockExpression):
            return RuntimeBlock(expression, environment)

        if isinstance(expression, ast.ListExpression):
            return [
                self.evaluate_expression(item, environment)
                for item in expression.items
            ]

        raise RuntimeHoomerError(
            expression.location,
            f"The interpreter does not know how to evaluate {type(expression).__name__}.",
        )

    def _define_function(
        self,
        definition: ast.FunctionDefinition,
        environment: Environment,
        active_module: RuntimeModule | None,
    ) -> object:
        runtime_function = RuntimeFunction(definition, environment)
        existing_value = environment.get_local(definition.name)

        if isinstance(existing_value, RuntimeFunction):
            function_group = FunctionGroup(definition.name, existing_value)
            function_group.add_overload(runtime_function, definition.location)
            environment.define(
                definition.name,
                function_group,
                replace=True,
                location=definition.location,
            )
            stored_function: object = function_group
        elif isinstance(existing_value, FunctionGroup):
            existing_value.add_overload(runtime_function, definition.location)
            stored_function = existing_value
        elif existing_value is not None or environment.has_local(definition.name):
            raise RuntimeHoomerError(
                definition.location,
                f"`{definition.name}` already names a non-function value in this scope.",
                expected="a unique function name",
                found=definition.name,
            )
        else:
            environment.define(
                definition.name,
                runtime_function,
                location=definition.location,
            )
            stored_function = runtime_function

        if active_module is not None:
            active_module.register_member(definition.name)
            if definition.is_public:
                active_module.make_public(definition.name)
        return stored_function

    def _define_struct(
        self,
        definition: ast.StructDefinition,
        environment: Environment,
        active_module: RuntimeModule | None,
    ) -> RuntimeStructDefinition:
        runtime_fields = [
            RuntimeFieldDefinition(field.name, field.default_value)
            for field in definition.fields
        ]
        runtime_struct = RuntimeStructDefinition(
            definition.name,
            runtime_fields,
            environment,
        )
        environment.define(
            definition.name,
            runtime_struct,
            is_mutable=False,
            location=definition.location,
        )
        if active_module is not None:
            active_module.register_member(definition.name)
            if definition.is_public:
                active_module.make_public(definition.name)
        return runtime_struct

    def _execute_module_definition(self, definition: ast.ModuleDefinition) -> RuntimeModule:
        runtime_module = self.module_registry.get_or_create_path(definition.name_path)
        self.execute_statements(
            definition.body,
            runtime_module.environment,
            active_module=runtime_module,
        )
        return runtime_module

    def _execute_import(
        self,
        statement: ast.ImportStatement,
        environment: Environment,
    ) -> object:
        self._load_import_if_needed(statement.name_path, statement.location)

        if statement.selected_names:
            source_module = self.module_registry.get(statement.name_path)
            if source_module is None:
                raise RuntimeHoomerError(
                    statement.location,
                    f"`{'.'.join(statement.name_path)}` is not a loaded module.",
                    expected="a module before `:` in a selected import",
                    found=".".join(statement.name_path),
                )

            for selected_name in statement.selected_names:
                imported_value = source_module.get_member(selected_name, statement.location)
                self._bind_imported_name(
                    environment,
                    selected_name,
                    imported_value,
                    statement.location,
                )
            return source_module

        # A dotted import has two useful interpretations. If the entire path is
        # a module, ``import Accounts.User`` binds that nested module. Otherwise
        # it binds public member ``User`` from module ``Accounts``. Trying the
        # exact module first preserves both forms without adding new syntax.
        exact_module = self.module_registry.get(statement.name_path)
        if exact_module is not None:
            local_name = statement.alias or statement.name_path[-1]
            self._bind_imported_name(
                environment,
                local_name,
                exact_module,
                statement.location,
            )
            return exact_module

        parent_path = statement.name_path[:-1]
        member_name = statement.name_path[-1]
        parent_module = self.module_registry.get(parent_path)
        if parent_module is None:
            raise RuntimeHoomerError(
                statement.location,
                f"Could not resolve import `{'.'.join(statement.name_path)}`.",
                expected="a module or public member available on the module search path",
                found=".".join(statement.name_path),
            )

        imported_value = parent_module.get_member(member_name, statement.location)
        local_name = statement.alias or member_name
        self._bind_imported_name(
            environment,
            local_name,
            imported_value,
            statement.location,
        )
        return imported_value

    @staticmethod
    def _bind_imported_name(
        environment: Environment,
        local_name: str,
        imported_value: object,
        location: SourceLocation,
    ) -> None:
        """Bind an import, accepting a registry-created identical module binding.

        Loading ``Application`` creates the root module in the global namespace
        before the import statement finishes. The import should reuse that same
        object, not report a duplicate name. A genuinely different existing
        value still goes through ``Environment.define`` and receives its normal
        collision diagnostic.
        """

        existing_value = environment.get_local(local_name)
        if environment.has_local(local_name) and existing_value is imported_value:
            return
        environment.define(local_name, imported_value, location=location)

    def _execute_if(
        self,
        statement: ast.IfStatement,
        environment: Environment,
        active_module: RuntimeModule | None,
    ) -> object:
        for branch in statement.branches:
            condition_value = self.evaluate_expression(branch.condition, environment)
            if is_truthy(condition_value):
                return self.execute_statements(
                    branch.body,
                    Environment(environment),
                    active_module,
                )

        if statement.else_body is None:
            return None
        return self.execute_statements(
            statement.else_body,
            Environment(environment),
            active_module,
        )

    def _execute_when(
        self,
        statement: ast.WhenStatement,
        environment: Environment,
        active_module: RuntimeModule | None,
    ) -> object:
        matched_value = self.evaluate_expression(statement.matched_expression, environment)

        for branch in statement.branches:
            if not self._pattern_matches(branch.pattern, matched_value, environment):
                continue

            branch_environment = Environment(environment)
            if statement.binding_name is not None:
                branch_environment.define(
                    statement.binding_name,
                    matched_value,
                    location=statement.location,
                )
            return self.execute_statements(branch.body, branch_environment, active_module)

        return None

    def _execute_for(
        self,
        statement: ast.ForStatement,
        environment: Environment,
        active_module: RuntimeModule | None,
    ) -> object:
        iterable_value = self.evaluate_expression(
            statement.iterable_expression,
            environment,
        )
        if not isinstance(iterable_value, list):
            raise RuntimeHoomerError(
                statement.iterable_expression.location,
                "A `for` loop currently iterates over a list.",
                expected="a list such as `[first, second]`",
                found=runtime_type_name(iterable_value),
            )

        last_value: object = None
        self._loop_depth += 1
        try:
            for item_value in iterable_value:
                iteration_environment = Environment(environment)
                iteration_environment.define(
                    statement.item_name,
                    item_value,
                    location=statement.location,
                )
                try:
                    last_value = self.execute_statements(
                        statement.body,
                        iteration_environment,
                        active_module,
                    )
                except ContinueLoop:
                    continue
        finally:
            self._loop_depth -= 1
        return last_value

    def _pattern_matches(
        self,
        pattern: ast.WhenPattern,
        matched_value: object,
        environment: Environment,
    ) -> bool:
        if isinstance(pattern, ast.WildcardPattern):
            return True
        if isinstance(pattern, ast.NilPattern):
            return matched_value is None
        if isinstance(pattern, ast.LiteralPattern):
            return matched_value == pattern.value
        if isinstance(pattern, ast.StructPattern):
            expected_struct = self._resolve_pattern_name_path(
                pattern.name_path,
                pattern.location,
                environment,
            )
            if not isinstance(expected_struct, RuntimeStructDefinition):
                pattern_name = ".".join(pattern.name_path)
                raise RuntimeHoomerError(
                    pattern.location,
                    f"Pattern `{pattern_name}` does not name a struct.",
                    expected="a struct name, literal, `nil`, or `_`",
                    found=runtime_type_name(expected_struct),
                )
            return (
                isinstance(matched_value, RuntimeStructInstance)
                and matched_value.definition is expected_struct
            )
        return False

    def _resolve_pattern_name_path(
        self,
        name_path: list[str],
        location: SourceLocation,
        environment: Environment,
    ) -> object:
        resolved_value = environment.get(name_path[0], location)
        for member_name in name_path[1:]:
            if not isinstance(resolved_value, RuntimeModule):
                resolved_prefix = ".".join(name_path[:-1])
                raise RuntimeHoomerError(
                    location,
                    f"`{resolved_prefix}` is not a module in this pattern.",
                    expected="a qualified struct name such as `Accounts.User`",
                    found=runtime_type_name(resolved_value),
                )
            resolved_value = resolved_value.get_member(member_name, location)
        return resolved_value

    def _evaluate_unary(
        self,
        expression: ast.UnaryExpression,
        environment: Environment,
    ) -> object:
        operand = self.evaluate_expression(expression.operand, environment)
        if expression.operator == "-" and self._is_number(operand):
            return -operand  # type: ignore[operator]

        raise RuntimeHoomerError(
            expression.location,
            f"Operator `{expression.operator}` cannot be applied to {runtime_type_name(operand)}.",
            expected="a number after unary `-`",
            found=runtime_type_name(operand),
        )

    def _evaluate_binary(
        self,
        expression: ast.BinaryExpression,
        environment: Environment,
    ) -> object:
        left_value = self.evaluate_expression(expression.left_operand, environment)
        right_value = self.evaluate_expression(expression.right_operand, environment)
        operator = expression.operator

        if operator == "==":
            return left_value == right_value
        if operator == "!=":
            return left_value != right_value

        both_are_numbers = self._is_number(left_value) and self._is_number(right_value)
        both_are_strings = isinstance(left_value, str) and isinstance(right_value, str)

        if operator == "+" and both_are_strings:
            return left_value + right_value  # type: ignore[operator]
        if operator == "+" and both_are_numbers:
            return left_value + right_value  # type: ignore[operator]
        if operator == "-" and both_are_numbers:
            return left_value - right_value  # type: ignore[operator]
        if operator == "*" and both_are_numbers:
            return left_value * right_value  # type: ignore[operator]
        if operator == "/" and both_are_numbers:
            if right_value == 0:
                raise RuntimeHoomerError(
                    expression.location,
                    "A number cannot be divided by zero.",
                    expected="a non-zero right operand",
                    found="0",
                )
            return left_value / right_value  # type: ignore[operator]

        operands_are_comparable = both_are_numbers or both_are_strings
        if operands_are_comparable:
            if operator == ">":
                return left_value > right_value  # type: ignore[operator]
            if operator == ">=":
                return left_value >= right_value  # type: ignore[operator]
            if operator == "<":
                return left_value < right_value  # type: ignore[operator]
            if operator == "<=":
                return left_value <= right_value  # type: ignore[operator]

        raise RuntimeHoomerError(
            expression.location,
            f"Operator `{operator}` cannot combine {runtime_type_name(left_value)} "
            f"and {runtime_type_name(right_value)}.",
            expected="two numbers, or two strings for a supported operation",
            found=f"{runtime_type_name(left_value)} and {runtime_type_name(right_value)}",
        )

    def _evaluate_assignment(
        self,
        expression: ast.AssignmentExpression,
        environment: Environment,
    ) -> object:
        assigned_value = self.evaluate_expression(expression.value, environment)
        if isinstance(expression.target, ast.VariableExpression):
            return environment.assign(
                expression.target.name,
                assigned_value,
                expression.target.location,
            )

        target_value = self.evaluate_expression(expression.target.target, environment)
        if isinstance(target_value, RuntimeStructInstance):
            return target_value.set_field(
                expression.target.field_name,
                assigned_value,
                expression.target.location,
            )

        raise RuntimeHoomerError(
            expression.target.location,
            f"Fields can only be assigned on struct instances, not {runtime_type_name(target_value)}.",
            expected="a struct field such as `user.name`",
            found=runtime_type_name(target_value),
        )

    def _evaluate_call(
        self,
        expression: ast.CallExpression,
        environment: Environment,
    ) -> object:
        callable_value = self.evaluate_expression(expression.callable_expression, environment)
        if (
            not expression.uses_parentheses
            and isinstance(callable_value, RuntimeStructDefinition)
        ):
            raise RuntimeHoomerError(
                expression.location,
                f"Struct `{callable_value.name}` construction always requires parentheses.",
                expected=f"`{callable_value.name}(field_name=value)`",
                found="a parenthesis-free struct call",
            )
        positional_arguments: list[object] = []
        named_arguments: dict[str, object] = {}
        encountered_named_argument = False

        for argument in expression.arguments:
            argument_value = self.evaluate_expression(argument.value, environment)
            if argument.name is None:
                if encountered_named_argument:
                    raise RuntimeHoomerError(
                        expression.location,
                        "A positional argument cannot follow a named argument.",
                        expected="all positional arguments before named arguments",
                        found="a positional argument after a named argument",
                    )
                positional_arguments.append(argument_value)
                continue

            encountered_named_argument = True
            if argument.name in named_arguments:
                raise RuntimeHoomerError(
                    expression.location,
                    f"Named argument `{argument.name}` was supplied more than once.",
                    expected="each named argument once",
                    found=argument.name,
                )
            named_arguments[argument.name] = argument_value

        call_method = getattr(callable_value, "call", None)
        if call_method is None:
            raise RuntimeHoomerError(
                expression.location,
                f"A value of type {runtime_type_name(callable_value)} cannot be called.",
                expected="a function, struct, or `do` block",
                found=runtime_type_name(callable_value),
            )
        return call_method(
            self,
            positional_arguments,
            named_arguments,
            expression.location,
        )

    def _read_field(
        self,
        target_value: object,
        field_name: str,
        location: SourceLocation,
    ) -> object:
        if isinstance(target_value, RuntimeStructInstance):
            return target_value.get_field(field_name, location)
        if isinstance(target_value, ReflectionValue):
            return target_value.get_field(field_name, location)
        if isinstance(target_value, RuntimeModule):
            return target_value.get_member(field_name, location)

        raise RuntimeHoomerError(
            location,
            f"A value of type {runtime_type_name(target_value)} has no fields.",
            expected="a struct instance, module, or reflection value",
            found=runtime_type_name(target_value),
        )

    def _interpolate_string(
        self,
        string_value: str,
        location: SourceLocation,
        environment: Environment,
    ) -> str:
        """Evaluate brace expressions using the normal Hoomer expression parser.

        Examples:

        * ``"Hello {user.name}"`` evaluates the field access in the current scope.
        * ``"{{literal braces}}"`` becomes ``"{literal braces}"``.

        A hand-written “name only” interpolator would be shorter, but it would
        make expressions behave differently inside strings. Reusing Lexer and
        Parser keeps one language model for programmers to learn.
        """

        if "{" not in string_value and "}" not in string_value:
            return string_value

        rendered_parts: list[str] = []
        current_index = 0

        while current_index < len(string_value):
            current_character = string_value[current_index]
            if current_character == "{" and self._character_at(string_value, current_index + 1) == "{":
                rendered_parts.append("{")
                current_index += 2
                continue
            if current_character == "}" and self._character_at(string_value, current_index + 1) == "}":
                rendered_parts.append("}")
                current_index += 2
                continue
            if current_character != "{":
                if current_character == "}":
                    self._raise_interpolation_error(location, "a closing `}` has no matching `{`")
                rendered_parts.append(current_character)
                current_index += 1
                continue

            closing_brace_index = string_value.find("}", current_index + 1)
            if closing_brace_index == -1:
                self._raise_interpolation_error(location, "an opening `{` has no matching `}`")

            expression_source = string_value[current_index + 1 : closing_brace_index].strip()
            if not expression_source:
                self._raise_interpolation_error(location, "empty braces do not contain an expression")

            try:
                interpolation_tokens = Lexer(expression_source, location.file_name).scan_tokens()
                interpolation_expression = Parser(interpolation_tokens).parse_single_expression()
                interpolation_value = self.evaluate_expression(interpolation_expression, environment)
            except HoomerError as error:
                raise RuntimeHoomerError(
                    location,
                    "The expression inside this string interpolation is invalid.\n\n"
                    f"{error.explanation}",
                    expected="a valid expression between `{` and `}`",
                    found=expression_source,
                ) from None

            rendered_parts.append(format_runtime_value(interpolation_value))
            current_index = closing_brace_index + 1

        return "".join(rendered_parts)

    def _raise_interpolation_error(
        self,
        location: SourceLocation,
        problem: str,
    ) -> None:
        raise RuntimeHoomerError(
            location,
            f"This string has invalid interpolation: {problem}.",
            expected="balanced braces, for example `Hello {user.name}`",
            found="an unbalanced interpolation marker",
        )

    def _load_import_if_needed(
        self,
        name_path: list[str],
        location: SourceLocation,
    ) -> None:
        exact_module_exists = self.module_registry.get(name_path) is not None
        parent_module_exists = (
            len(name_path) > 1 and self.module_registry.get(name_path[:-1]) is not None
        )
        if exact_module_exists or parent_module_exists:
            return

        relative_candidates = [Path(*name_path).with_suffix(".hmr")]
        snake_case_path = [self._module_name_to_file_name(name) for name in name_path]
        relative_candidates.append(Path(*snake_case_path).with_suffix(".hmr"))
        if len(name_path) > 1:
            relative_candidates.append(Path(*name_path[:-1]).with_suffix(".hmr"))
            relative_candidates.append(Path(*snake_case_path[:-1]).with_suffix(".hmr"))
        relative_candidates.append(Path(name_path[0]).with_suffix(".hmr"))
        relative_candidates.append(Path(snake_case_path[0]).with_suffix(".hmr"))

        # Preserve candidate order while removing duplicates. The most specific
        # file wins: importing ``Accounts.User`` first tries
        # ``Accounts/User.hmr``, then ``Accounts.hmr`` where User may be a member.
        unique_candidates = list(dict.fromkeys(relative_candidates))
        for search_path in self.module_search_paths:
            for relative_candidate in unique_candidates:
                source_path = (search_path / relative_candidate).resolve()
                if not source_path.is_file():
                    continue
                self._execute_import_file(source_path, location)
                return

        searched_locations = [
            str(search_path / candidate)
            for search_path in self.module_search_paths
            for candidate in unique_candidates
        ]
        raise RuntimeHoomerError(
            location,
            f"Could not find import `{'.'.join(name_path)}`.",
            expected="a loaded module or one of:\n    " + "\n    ".join(searched_locations),
            found="no matching .hmr file",
        )

    @staticmethod
    def _module_name_to_file_name(module_name: str) -> str:
        """Map ``LoginService`` to the conventional ``login_service`` filename."""

        words_separated_before_capitals = re.sub(
            r"(.)([A-Z][a-z]+)",
            r"\1_\2",
            module_name,
        )
        return re.sub(
            r"([a-z0-9])([A-Z])",
            r"\1_\2",
            words_separated_before_capitals,
        ).lower()

    def _execute_import_file(self, source_path: Path, location: SourceLocation) -> None:
        if source_path in self._loaded_files:
            return
        if source_path in self._files_being_loaded:
            raise RuntimeHoomerError(
                location,
                f"Importing `{source_path}` creates a circular import.",
                expected="modules whose imports do not loop back to a file still loading",
                found=str(source_path),
            )

        self._files_being_loaded.add(source_path)
        try:
            self.execute_file(source_path)
        finally:
            self._files_being_loaded.remove(source_path)

    def _install_builtins(self) -> None:
        reflect_function = NativeFunction(
            "reflect",
            self._native_reflect,
            ["value"],
        )
        self.global_environment.define("reflect", reflect_function, is_mutable=False)

        text_environment = Environment(self.global_environment)
        text_module = RuntimeModule("Text", text_environment, is_builtin=True)
        text_functions = [
            NativeFunction("trim", self._native_trim, ["text"]),
            NativeFunction("lowercase", self._native_lowercase, ["text"]),
        ]
        for function in text_functions:
            text_environment.define(function.name, function, is_mutable=False)
            text_module.make_public(function.name)
        self.module_registry.register_builtin(text_module)

    def _native_reflect(
        self,
        interpreter: Interpreter,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> ReflectionValue:
        value = self._one_native_argument(
            "reflect",
            "value",
            positional_arguments,
            named_arguments,
            location,
        )
        return reflect_runtime_value(value)

    def _native_trim(
        self,
        interpreter: Interpreter,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> str:
        value = self._one_native_argument(
            "trim",
            "text",
            positional_arguments,
            named_arguments,
            location,
        )
        return self._require_string_argument("trim", value, location).strip()

    def _native_lowercase(
        self,
        interpreter: Interpreter,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> str:
        value = self._one_native_argument(
            "lowercase",
            "text",
            positional_arguments,
            named_arguments,
            location,
        )
        return self._require_string_argument("lowercase", value, location).lower()

    def _one_native_argument(
        self,
        function_name: str,
        parameter_name: str,
        positional_arguments: list[object],
        named_arguments: dict[str, object],
        location: SourceLocation,
    ) -> object:
        has_one_positional = len(positional_arguments) == 1 and not named_arguments
        has_one_named = not positional_arguments and set(named_arguments) == {parameter_name}
        if has_one_positional:
            return positional_arguments[0]
        if has_one_named:
            return named_arguments[parameter_name]

        supplied_count = len(positional_arguments) + len(named_arguments)
        raise RuntimeHoomerError(
            location,
            f"Function `{function_name}` expects one `{parameter_name}` argument.",
            expected=f"`{function_name}({parameter_name})`",
            found=f"{supplied_count} argument(s)",
        )

    def _require_string_argument(
        self,
        function_name: str,
        value: object,
        location: SourceLocation,
    ) -> str:
        if isinstance(value, str):
            return value
        raise RuntimeHoomerError(
            location,
            f"Function `{function_name}` only accepts a string.",
            expected="string",
            found=runtime_type_name(value),
        )

    @staticmethod
    def _is_number(value: object) -> bool:
        # Python's ``bool`` is a subclass of ``int``. Hoomer deliberately keeps
        # booleans and numbers separate, so ``true + 1`` must not become ``2``.
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    @staticmethod
    def _character_at(text: str, index: int) -> str | None:
        if index >= len(text):
            return None
        return text[index]
