"""Tree-walking evaluation for parsed Hoomer programs."""

from __future__ import annotations

import io
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from hoomer import ast
from hoomer.errors import HoomerError, PackageContentError, RuntimeHoomerError, SourceLocation
from hoomer.lexer import Lexer
from hoomer.naming import SNAKE_CASE_PATTERN
from hoomer.parser import Parser
from hoomer.runtime.environment import Environment
from hoomer.runtime.functions import (
    NativeFunction,
    ReturnFromFunction,
    RuntimeBlock,
    RuntimeFunction,
)
from hoomer.runtime.packages import PackageRegistry, RuntimePackage
from hoomer.runtime.reflection import ReflectionValue, reflect_runtime_value
from hoomer.runtime.structs import (
    RuntimeFieldDefinition,
    RuntimeStructDefinition,
    RuntimeStructInstance,
)
from hoomer.runtime.values import format_runtime_value, runtime_type_name


class ContinueLoop(Exception):
    """Internal control-flow signal consumed by the nearest running loop."""


class Interpreter:
    """Own runtime state and evaluate Hoomer AST nodes.

    One interpreter instance is one Hoomer process. Its global environment,
    package registry, and import cache intentionally survive multiple
    ``execute_source`` calls. That lets the REPL remember earlier lines and
    avoids loading the same package twice.
    """

    def __init__(
        self,
        *,
        output: TextIO | None = None,
        package_search_paths: Iterable[str | Path] | None = None,
    ) -> None:
        self.output = output or sys.stdout
        self.global_environment = Environment()
        self.package_registry = PackageRegistry(self.global_environment)
        self.package_search_paths = [
            Path(search_path).resolve()
            for search_path in (package_search_paths or [Path.cwd()])
        ]
        self.project_root: Path | None = None
        self._package_directories_being_loaded: set[Path] = set()
        self._package_paths_being_loaded: set[str] = set()
        self._loaded_package_directories: dict[Path, RuntimePackage] = {}
        self._function_call_depth = 0
        self._loop_depth = 0
        self._install_builtins()

    @classmethod
    def capture_output(
        cls,
        *,
        package_search_paths: Iterable[str | Path] | None = None,
    ) -> tuple[Interpreter, io.StringIO]:
        """Convenience constructor for tests and embedding applications."""

        output_buffer = io.StringIO()
        return (
            cls(output=output_buffer, package_search_paths=package_search_paths),
            output_buffer,
        )

    def execute_source(self, source_code: str, file_name: str = "<source>") -> object:
        program = self._parse_source(source_code, file_name)
        return self.execute_program(program)

    def execute_file(self, file_path: str | Path) -> object:
        resolved_path = Path(file_path).resolve()
        raise PackageContentError(
            SourceLocation(str(resolved_path), 1, 1),
            "An individual package file cannot be executed.",
            expected=f"the package directory `{resolved_path.parent}`",
            found=str(resolved_path),
        )

    def execute_package(self, package_directory: str | Path) -> object:
        resolved_directory = Path(package_directory).resolve()
        import_path = self._prepare_local_package(resolved_directory)
        return self._load_package_directory(
            resolved_directory,
            import_path,
            SourceLocation(str(package_directory), 1, 1),
            invoke_main=True,
        )

    def check_package(self, package_directory: str | Path) -> object:
        resolved_directory = Path(package_directory).resolve()
        import_path = self._prepare_local_package(resolved_directory)
        return self._load_package_directory(
            resolved_directory,
            import_path,
            SourceLocation(str(package_directory), 1, 1),
            invoke_main=False,
        )

    @staticmethod
    def _parse_source(source_code: str, file_name: str) -> ast.Program:
        tokens = Lexer(source_code, file_name).scan_tokens()
        return Parser(tokens).parse()

    def _parse_file(self, resolved_path: Path) -> ast.Program:
        source_code = resolved_path.read_text(encoding="utf-8")
        return self._parse_source(source_code, str(resolved_path))

    def execute_program(self, program: ast.Program) -> object:
        try:
            if program.package_name is not None:
                import_path = self._package_name_to_directory_name(program.package_name)
                return self._install_package_programs(
                    [program],
                    import_path=import_path,
                    source_directory=None,
                )
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

    def _prepare_local_package(self, package_directory: Path) -> str:
        discovered_root = self._find_project_root(package_directory)
        if self.project_root is None:
            self.project_root = discovered_root
        elif self.project_root != discovered_root:
            raise PackageContentError(
                SourceLocation(str(package_directory), 1, 1),
                "One interpreter process cannot run packages from two project roots.",
                expected=str(self.project_root),
                found=str(discovered_root),
            )

        project_root_name = self.project_root.name
        if SNAKE_CASE_PATTERN.fullmatch(project_root_name) is None:
            raise PackageContentError(
                SourceLocation(str(self.project_root), 1, 1),
                "A project-root directory name must use snake_case.",
                expected="a name such as `kenekoi` or `billing_service`",
                found=project_root_name,
            )

        if self.project_root.parent not in self.package_search_paths:
            self.package_search_paths.append(self.project_root.parent)

        relative_directory = package_directory.relative_to(self.project_root)
        relative_parts = list(relative_directory.parts)
        invalid_part = None
        for part in relative_parts:
            if SNAKE_CASE_PATTERN.fullmatch(part) is None:
                invalid_part = part
                break
        if invalid_part is not None:
            raise PackageContentError(
                SourceLocation(str(package_directory), 1, 1),
                "Directories inside a Hoomer package path must use snake_case.",
                expected="path segments such as `accounts` or `login_service`",
                found=invalid_part,
            )

        return "/".join([project_root_name, *relative_parts])

    @staticmethod
    def _find_project_root(package_directory: Path) -> Path:
        for candidate in (package_directory, *package_directory.parents):
            if (candidate / "hoomer.toml").is_file():
                return candidate

        # A package can still be run before a project manifest exists. It acts
        # as a single-package project whose root is the package directory.
        return package_directory

    def _load_package_directory(
        self,
        package_directory: Path,
        import_path: str,
        location: SourceLocation,
        *,
        invoke_main: bool,
    ) -> object:
        if not package_directory.is_dir():
            raise PackageContentError(
                location,
                "Hoomer executes packages as directories, not individual files.",
                expected="a directory containing .hmr package files",
                found=str(package_directory),
            )

        loaded_package = self._loaded_package_directories.get(package_directory)
        if loaded_package is not None:
            if loaded_package.import_path != import_path:
                raise PackageContentError(
                    location,
                    "One package directory cannot have two import paths.",
                    expected=loaded_package.import_path,
                    found=import_path,
                )
            return self._invoke_main(loaded_package) if invoke_main else loaded_package

        source_paths = sorted(package_directory.glob("*.hmr"))
        if not source_paths:
            raise PackageContentError(
                location,
                "This directory does not contain a Hoomer package.",
                expected="at least one .hmr file",
                found=str(package_directory),
            )

        programs = [self._parse_file(source_path) for source_path in source_paths]
        self._validate_package_files(package_directory, programs)

        if package_directory in self._package_directories_being_loaded:
            raise RuntimeHoomerError(
                location,
                f"Importing package `{import_path}` creates a circular import.",
                expected="packages whose imports do not loop back to a package still loading",
                found=import_path,
            )

        existing_package = self.package_registry.get(import_path)
        package_comes_from_another_directory = (
            existing_package is not None
            and existing_package.source_directory is not None
            and existing_package.source_directory != package_directory
        )
        if package_comes_from_another_directory:
            raise PackageContentError(
                programs[0].package_location or location,
                f"Import path `{import_path}` is already defined by another directory.",
                expected=str(existing_package.source_directory),
                found=str(package_directory),
            )

        self._package_directories_being_loaded.add(package_directory)
        self._package_paths_being_loaded.add(import_path)
        try:
            runtime_package = self._install_package_programs(
                programs,
                import_path=import_path,
                source_directory=package_directory,
            )
            self._loaded_package_directories[package_directory] = runtime_package
        except Exception:
            if existing_package is None:
                self.package_registry.discard(import_path)
            raise
        finally:
            self._package_directories_being_loaded.remove(package_directory)
            self._package_paths_being_loaded.remove(import_path)

        return self._invoke_main(runtime_package) if invoke_main else runtime_package

    def _validate_package_files(
        self,
        package_directory: Path,
        programs: list[ast.Program],
    ) -> None:
        first_program = programs[0]
        if first_program.package_name is None:
            raise PackageContentError(
                SourceLocation(first_program.statements[0].location.file_name, 1, 1)
                if first_program.statements
                else SourceLocation(str(package_directory), 1, 1),
                "Every .hmr file must begin with a package declaration.",
                expected="`package PackageName` on the first meaningful line",
                found="a file without a package declaration",
            )

        expected_name = first_program.package_name
        for program in programs[1:]:
            if program.package_name == expected_name:
                continue
            found_name = program.package_name or "no package declaration"
            raise PackageContentError(
                program.package_location
                or SourceLocation(str(package_directory), 1, 1),
                "Every .hmr file in a directory must declare the same package.",
                expected="package " + expected_name,
                found=found_name,
            )

        expected_directory_name = self._package_name_to_directory_name(expected_name)
        if package_directory.name.casefold() != expected_directory_name.casefold():
            raise PackageContentError(
                first_program.package_location
                or SourceLocation(str(package_directory), 1, 1),
                "A package name must agree with its directory name.",
                expected=expected_directory_name,
                found=package_directory.name,
            )

    def _install_package_programs(
        self,
        programs: list[ast.Program],
        *,
        import_path: str,
        source_directory: Path | None,
    ) -> RuntimePackage:
        package_name = programs[0].package_name
        if package_name is None:
            raise ValueError("Package programs must have a package declaration.")

        self._validate_unique_package_declarations(programs)
        runtime_package = self.package_registry.get_or_create(
            package_name,
            import_path,
            source_directory=source_directory,
        )
        file_environments = [Environment(runtime_package.environment) for _ in programs]

        for program, file_environment in zip(programs, file_environments, strict=True):
            for statement in program.statements:
                if isinstance(statement, ast.ImportStatement):
                    self.execute_statement(statement, file_environment)

        for program, file_environment in zip(programs, file_environments, strict=True):
            for statement in program.statements:
                if isinstance(statement, (ast.FunctionDefinition, ast.StructDefinition)):
                    self.execute_statement(statement, file_environment, runtime_package)

        for program, file_environment in zip(programs, file_environments, strict=True):
            for statement in program.statements:
                if self._is_constant_declaration(statement):
                    self._define_package_constant(
                        statement.expression,
                        file_environment,
                        runtime_package,
                    )

        return runtime_package

    def _validate_unique_package_declarations(self, programs: list[ast.Program]) -> None:
        declarations: dict[str, SourceLocation] = {}
        for program in programs:
            for statement in program.statements:
                declaration_name = self._package_declaration_name(statement)
                if declaration_name is None:
                    continue
                first_location = declarations.get(declaration_name)
                if first_location is not None:
                    raise PackageContentError(
                        statement.location,
                        f"Package declaration `{declaration_name}` is duplicated.",
                        expected=(
                            f"one declaration; the first is in {first_location.file_name} "
                            f"at line {first_location.line}"
                        ),
                        found=f"another `{declaration_name}` declaration",
                    )
                declarations[declaration_name] = statement.location

    @staticmethod
    def _package_declaration_name(statement: ast.Statement) -> str | None:
        if isinstance(statement, (ast.FunctionDefinition, ast.StructDefinition)):
            return statement.name
        if Interpreter._is_constant_declaration(statement):
            return statement.expression.target.name
        return None

    @staticmethod
    def _is_constant_declaration(statement: ast.Statement) -> bool:
        if not isinstance(statement, ast.ExpressionStatement):
            return False
        expression = statement.expression
        return (
            isinstance(expression, ast.AssignmentExpression)
            and isinstance(expression.target, ast.VariableExpression)
            and expression.target.name.isupper()
        )

    def _define_package_constant(
        self,
        expression: ast.AssignmentExpression,
        file_environment: Environment,
        runtime_package: RuntimePackage,
    ) -> object:
        constant_name = expression.target.name
        constant_value = self.evaluate_expression(expression.value, file_environment)
        runtime_package.environment.define(
            constant_name,
            constant_value,
            is_mutable=False,
            location=expression.location,
        )
        runtime_package.make_public(constant_name)
        return constant_value

    def _invoke_main(self, runtime_package: RuntimePackage) -> object:
        main_function = runtime_package.environment.get_local("main")
        if main_function is None:
            return runtime_package
        if not isinstance(main_function, RuntimeFunction):
            package_location = str(
                runtime_package.source_directory or runtime_package.import_path
            )
            raise RuntimeHoomerError(
                SourceLocation(package_location, 1, 1),
                f"Package `{runtime_package.import_path}` has a non-function named `main`.",
                expected="a parameterless `fn main ... end` declaration",
                found=runtime_type_name(main_function),
            )
        if not main_function.accepts_arguments(0, set()):
            raise RuntimeHoomerError(
                main_function.definition.location,
                "A package entry point must be callable without arguments.",
                expected="`fn main` or `fn main()`",
                found=main_function.signature,
            )
        return main_function.call(
            self,
            [],
            {},
            main_function.definition.location,
        )

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
                return self.execute_statements(
                    statements,
                    environment,
                    result_is_used=True,
                )
            except ReturnFromFunction as return_signal:
                return return_signal.value
        finally:
            self._loop_depth = enclosing_loop_depth
            self._function_call_depth -= 1

    def execute_statements(
        self,
        statements: list[ast.Statement],
        environment: Environment,
        active_package: RuntimePackage | None = None,
        *,
        result_is_used: bool = False,
    ) -> object:
        last_value: object = None
        final_statement_index = len(statements) - 1
        for statement_index, statement in enumerate(statements):
            statement_result_is_used = (
                result_is_used and statement_index == final_statement_index
            )
            last_value = self.execute_statement(
                statement,
                environment,
                active_package,
                result_is_used=statement_result_is_used,
            )
        return last_value

    def execute_statement(
        self,
        statement: ast.Statement,
        environment: Environment,
        active_package: RuntimePackage | None = None,
        *,
        result_is_used: bool = False,
    ) -> object:
        if isinstance(statement, ast.ExpressionStatement):
            expression = statement.expression
            if isinstance(expression, ast.CallExpression):
                callable_value = self.evaluate_expression(
                    expression.callable_expression,
                    environment,
                )
                result_is_discarded = not result_is_used
                if self._is_fallible_callable(callable_value) and result_is_discarded:
                    raise RuntimeHoomerError(
                        expression.location,
                        f"The result of fallible function "
                        f"`{callable_value.name}` is discarded.",
                        expected=(
                            "handle it with `when`, store or return it, "
                            "or explicitly `ignore` it"
                        ),
                        found=f"an unused call to `{callable_value.name}`",
                    )
                expression_value = self._call_value(
                    expression,
                    environment,
                    callable_value,
                )
            elif isinstance(expression, ast.WhenExpression):
                expression_value = self._evaluate_when(
                    expression,
                    environment,
                    result_is_used=result_is_used,
                )
            else:
                expression_value = self.evaluate_expression(expression, environment)
            return expression_value

        if isinstance(statement, ast.IgnoreStatement):
            callable_value = self.evaluate_expression(
                statement.expression.callable_expression,
                environment,
            )
            if not self._is_fallible_callable(callable_value):
                raise RuntimeHoomerError(
                    statement.location,
                    "`ignore` is reserved for deliberately discarded fallible results.",
                    expected="a function ending in `!`",
                    found=runtime_type_name(callable_value),
                )
            self._call_value(statement.expression, environment, callable_value)
            return None

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
            return self._define_function(statement, environment, active_package)

        if isinstance(statement, ast.StructDefinition):
            return self._define_struct(statement, environment, active_package)

        if isinstance(statement, ast.ImportStatement):
            return self._execute_import(statement, environment)

        if isinstance(statement, ast.IfStatement):
            return self._execute_if(
                statement,
                environment,
                active_package,
                result_is_used=result_is_used,
            )

        if isinstance(statement, ast.ForStatement):
            return self._execute_for(statement, environment, active_package)

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
                return self._interpolate_string(
                    expression.value,
                    expression.location,
                    environment,
                )
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

        if isinstance(expression, ast.RangeExpression):
            return self._evaluate_range(expression, environment)

        if isinstance(expression, ast.WhenExpression):
            return self._evaluate_when(expression, environment)

        if isinstance(expression, ast.InlineWhenExpression):
            return self._evaluate_inline_when(expression, environment)

        raise RuntimeHoomerError(
            expression.location,
            f"The interpreter does not know how to evaluate {type(expression).__name__}.",
        )

    def _define_function(
        self,
        definition: ast.FunctionDefinition,
        environment: Environment,
        active_package: RuntimePackage | None,
    ) -> object:
        declaration_environment = (
            active_package.environment if active_package is not None else environment
        )
        if declaration_environment.has_local(definition.name):
            raise RuntimeHoomerError(
                definition.location,
                f"Function `{definition.name}` is already defined in this scope.",
                expected="a unique function name",
                found=definition.name,
            )

        runtime_function = RuntimeFunction(definition, environment)
        declaration_environment.define(
            definition.name,
            runtime_function,
            location=definition.location,
        )

        if active_package is not None:
            active_package.register_member(definition.name)
            if definition.is_public:
                active_package.make_public(definition.name)
        return runtime_function

    def _define_struct(
        self,
        definition: ast.StructDefinition,
        environment: Environment,
        active_package: RuntimePackage | None,
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
        declaration_environment = (
            active_package.environment if active_package is not None else environment
        )
        declaration_environment.define(
            definition.name,
            runtime_struct,
            is_mutable=False,
            location=definition.location,
        )
        if active_package is not None:
            active_package.register_member(definition.name)
            if definition.is_public:
                active_package.make_public(definition.name)
        return runtime_struct

    def _execute_import(
        self,
        statement: ast.ImportStatement,
        environment: Environment,
    ) -> object:
        source_package = self._load_import_if_needed(
            statement.package_path,
            statement.location,
        )

        if statement.selected_names:
            for selected_name in statement.selected_names:
                imported_value = source_package.get_member(selected_name, statement.location)
                self._bind_imported_name(
                    environment,
                    selected_name,
                    imported_value,
                    statement.location,
                )
            return source_package

        local_name = statement.alias or source_package.name
        self._bind_imported_name(
            environment,
            local_name,
            source_package,
            statement.location,
        )
        return source_package

    @staticmethod
    def _bind_imported_name(
        environment: Environment,
        local_name: str,
        imported_value: object,
        location: SourceLocation,
    ) -> None:
        """Bind one imported name in the current file scope."""

        existing_value = environment.get_local(local_name)
        if environment.has_local(local_name) and existing_value is imported_value:
            return
        environment.define(local_name, imported_value, location=location)

    def _execute_if(
        self,
        statement: ast.IfStatement,
        environment: Environment,
        active_package: RuntimePackage | None,
        *,
        result_is_used: bool,
    ) -> object:
        for branch in statement.branches:
            condition_value = self.evaluate_expression(branch.condition, environment)
            if not isinstance(condition_value, bool):
                raise RuntimeHoomerError(
                    branch.condition.location,
                    "An `if` condition must produce a boolean.",
                    expected="`true` or `false`",
                    found=runtime_type_name(condition_value),
                )
            if condition_value:
                return self.execute_statements(
                    branch.body,
                    Environment(environment),
                    active_package,
                    result_is_used=result_is_used,
                )

        if statement.else_body is None:
            return None
        return self.execute_statements(
            statement.else_body,
            Environment(environment),
            active_package,
            result_is_used=result_is_used,
        )

    def _evaluate_when(
        self,
        expression: ast.WhenExpression,
        environment: Environment,
        *,
        result_is_used: bool = True,
    ) -> object:
        matched_value = self.evaluate_expression(expression.matched_expression, environment)

        for branch in expression.branches:
            if not self._pattern_matches(branch.pattern, matched_value, environment):
                continue

            branch_environment = Environment(environment)
            if branch.binding_name is not None:
                branch_environment.define(
                    branch.binding_name,
                    matched_value,
                    location=branch.pattern.location,
                )
            return self.execute_statements(
                branch.body,
                branch_environment,
                result_is_used=result_is_used,
            )

        raise RuntimeHoomerError(
            expression.location,
            "No branch matched this `when` value.",
            expected="the required final `else` branch to match",
            found=runtime_type_name(matched_value),
        )

    def _evaluate_inline_when(
        self,
        expression: ast.InlineWhenExpression,
        environment: Environment,
    ) -> object:
        matched_value = self.evaluate_expression(
            expression.matched_expression,
            environment,
        )
        if self._pattern_matches(expression.pattern, matched_value, environment):
            return matched_value

        if expression.fallback_expression is None:
            return None
        return self.evaluate_expression(expression.fallback_expression, environment)

    def _execute_for(
        self,
        statement: ast.ForStatement,
        environment: Environment,
        active_package: RuntimePackage | None,
    ) -> object:
        iterable_value = self.evaluate_expression(
            statement.iterable_expression,
            environment,
        )
        if not isinstance(iterable_value, (list, range)):
            raise RuntimeHoomerError(
                statement.iterable_expression.location,
                "A `for` loop iterates over a list or range.",
                expected=(
                    "a list such as `[first, second]` or "
                    "a range such as `0..10`"
                ),
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
                        active_package,
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
        if isinstance(pattern, ast.ElsePattern):
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
                    expected="a struct name, literal, `nil`, or `else`",
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
            if not isinstance(resolved_value, RuntimePackage):
                resolved_prefix = ".".join(name_path[:-1])
                raise RuntimeHoomerError(
                    location,
                    f"`{resolved_prefix}` is not a package in this pattern.",
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

    def _evaluate_range(
        self,
        expression: ast.RangeExpression,
        environment: Environment,
    ) -> range:
        first_value = self.evaluate_expression(expression.first_value, environment)
        last_value = self.evaluate_expression(expression.last_value, environment)

        first_is_integer = self._is_integer(first_value)
        last_is_integer = self._is_integer(last_value)
        bounds_are_integers = first_is_integer and last_is_integer
        if not bounds_are_integers:
            raise RuntimeHoomerError(
                expression.location,
                "A range must start and end with whole numbers.",
                expected="two integers, such as `0..10`",
                found=(
                    f"{format_runtime_value(first_value, nested=True)} and "
                    f"{format_runtime_value(last_value, nested=True)}"
                ),
            )

        direction = 1 if first_value <= last_value else -1
        inclusive_stop = last_value + direction
        return range(first_value, inclusive_stop, direction)

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
        return self._call_value(expression, environment, callable_value)

    def _call_value(
        self,
        expression: ast.CallExpression,
        environment: Environment,
        callable_value: object,
    ) -> object:
        if (
            not expression.uses_parentheses
            and isinstance(callable_value, RuntimeStructDefinition)
        ):
            raise RuntimeHoomerError(
                expression.location,
                f"Struct `{callable_value.name}` construction always requires parentheses.",
                expected=f"`{callable_value.name}(field_name: value)`",
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

    @staticmethod
    def _is_fallible_callable(callable_value: object) -> bool:
        return (
            isinstance(callable_value, RuntimeFunction)
            and callable_value.is_fallible
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
        if isinstance(target_value, RuntimePackage):
            return target_value.get_member(field_name, location)

        raise RuntimeHoomerError(
            location,
            f"A value of type {runtime_type_name(target_value)} has no fields.",
            expected="a struct instance, package, or reflection value",
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
        import_path: str,
        location: SourceLocation,
    ) -> RuntimePackage:
        if import_path in self._package_paths_being_loaded:
            raise RuntimeHoomerError(
                location,
                f"Importing package `{import_path}` creates a circular import.",
                expected="packages whose imports do not loop back to a package still loading",
                found=import_path,
            )

        loaded_package = self.package_registry.get(import_path)
        if loaded_package is not None:
            return loaded_package

        package_directory, searched_locations = self._resolve_import_directory(
            import_path
        )
        if package_directory is not None:
            loaded_value = self._load_package_directory(
                package_directory,
                import_path,
                location,
                invoke_main=False,
            )
            if not isinstance(loaded_value, RuntimePackage):
                raise RuntimeHoomerError(
                    location,
                    f"Import `{import_path}` did not load a package value.",
                )
            return loaded_value

        expected_import = "a project package or installed package"
        if self.project_root is not None:
            local_candidate = self.project_root.joinpath(*import_path.split("/"))
            if self._directory_contains_package(local_candidate):
                expected_import = (
                    f"`{self.project_root.name}/{import_path}` for the local package"
                )
        if searched_locations:
            expected_import += ", or one of:\n    " + "\n    ".join(
                searched_locations
            )

        raise RuntimeHoomerError(
            location,
            f"Could not find import `{import_path}`.",
            expected=expected_import,
            found="no matching package directory",
        )

    def _resolve_import_directory(
        self,
        import_path: str,
    ) -> tuple[Path | None, list[str]]:
        path_parts = import_path.split("/")
        project_root_name = (
            self.project_root.name if self.project_root is not None else None
        )
        is_local_import = project_root_name == path_parts[0]

        if is_local_import:
            relative_parts = path_parts[1:]
            package_directory = self.project_root.joinpath(*relative_parts)
            searched_locations = [str(package_directory)]
            if self._directory_contains_package(package_directory):
                return package_directory.resolve(), searched_locations
            return None, searched_locations

        candidates: list[Path] = []
        for search_path in self.package_search_paths:
            search_path_is_inside_project = (
                self.project_root is not None
                and search_path.is_relative_to(self.project_root)
            )
            if search_path_is_inside_project:
                # Local packages must include the project-root segment. A
                # search path must not turn `accounts` into an implicit local
                # import when the real identity is `kenekoi/accounts`.
                continue
            if search_path.name == path_parts[0]:
                candidates.append(search_path.joinpath(*path_parts[1:]))
            else:
                candidates.append(search_path.joinpath(*path_parts))

        resolved_candidates = [candidate.resolve() for candidate in candidates]
        unique_candidates = list(dict.fromkeys(resolved_candidates))
        for candidate in unique_candidates:
            if self._directory_contains_package(candidate):
                return candidate, [str(path) for path in unique_candidates]
        return None, [str(path) for path in unique_candidates]

    @staticmethod
    def _directory_contains_package(directory: Path) -> bool:
        return directory.is_dir() and any(directory.glob("*.hmr"))

    @staticmethod
    def _package_name_to_directory_name(package_name: str) -> str:
        """Map ``LoginService`` to its conventional ``login_service`` directory."""

        words_separated_before_capitals = re.sub(
            r"(.)([A-Z][a-z]+)",
            r"\1_\2",
            package_name,
        )
        return re.sub(
            r"([a-z0-9])([A-Z])",
            r"\1_\2",
            words_separated_before_capitals,
        ).lower()

    def _install_builtins(self) -> None:
        reflect_function = NativeFunction(
            "reflect",
            self._native_reflect,
            ["value"],
        )
        self.global_environment.define("reflect", reflect_function, is_mutable=False)

        text_environment = Environment(self.global_environment)
        text_package = RuntimePackage(
            "Text",
            "text",
            text_environment,
            is_builtin=True,
        )
        text_functions = [
            NativeFunction("trim", self._native_trim, ["text"]),
            NativeFunction("lowercase", self._native_lowercase, ["text"]),
        ]
        for function in text_functions:
            text_environment.define(function.name, function, is_mutable=False)
            text_package.make_public(function.name)
        self.package_registry.register_builtin(text_package)

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
    def _is_integer(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    @staticmethod
    def _character_at(text: str, index: int) -> str | None:
        if index >= len(text):
            return None
        return text[index]
