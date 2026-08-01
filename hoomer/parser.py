"""Recursive-descent parser for Hoomer's newline-oriented grammar."""

from __future__ import annotations

from collections.abc import Callable

from hoomer import ast
from hoomer.errors import PackageContentError, ParserError
from hoomer.naming import (
    CONSTANT_CASE_PATTERN,
    PASCAL_CASE_PATTERN,
    validate_field_name,
    validate_function_name,
    validate_package_name,
    validate_package_path_segment,
    validate_struct_name,
    validate_variable_name,
)
from hoomer.tokens import Token, TokenType


class Parser:
    """Turn tokens into an AST using one method per grammar precedence level."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.current_index = 0

    def parse(self) -> ast.Program:
        statements: list[ast.Statement] = []
        self._skip_newlines()

        package_name = None
        package_location = None
        if self._match(TokenType.PACKAGE):
            package_token = self._previous()
            package_name = self._parse_package_header()
            package_location = package_token.location
            self._skip_newlines()

        while not self._is_at_end():
            statements.append(self._parse_statement())
            self._finish_statement()
            self._skip_newlines()

        self._validate_unique_function_names(statements)
        if package_name is not None:
            self._validate_package_contains_declarations_only(statements)
        return ast.Program(statements, package_name, package_location)

    def parse_single_expression(self) -> ast.Expression:
        """Parse source used inside ``"...{interpolation}..."``.

        Reusing the normal expression grammar is important. A smaller, custom
        interpolation evaluator would make ``{user.name}`` work differently
        from the same expression outside a string, an inconsistency that users
        would have to remember.
        """

        self._skip_newlines()
        expression = self._parse_expression()
        self._skip_newlines()
        self._consume(
            TokenType.END_OF_FILE,
            "Interpolation must contain exactly one expression.",
            "the end of the interpolation",
        )
        return expression

    def _parse_statement(self) -> ast.Statement:
        if self._match(TokenType.PUBLIC):
            return self._parse_public_definition()
        if self._match(TokenType.PACKAGE):
            package_token = self._previous()
            raise ParserError(
                package_token.location,
                "A package declaration must be the first meaningful line of its file.",
                expected="one `package PackageName` header per file",
                found="another `package` declaration",
            )
        if self._match(TokenType.IMPORT):
            return self._parse_import(self._previous())
        if self._match(TokenType.STRUCT):
            return self._parse_struct_definition(self._previous(), is_public=False)
        if self._match(TokenType.FUNCTION):
            return self._parse_function_definition(self._previous(), is_public=False)
        if self._match(TokenType.IF):
            return self._parse_if_statement(self._previous())
        if self._match(TokenType.RETURN):
            return self._parse_return_statement(self._previous())
        if self._match(TokenType.IGNORE):
            return self._parse_ignore_statement(self._previous())
        if self._match(TokenType.FOR):
            return self._parse_for_statement(self._previous())
        if self._match(TokenType.CONTINUE):
            continue_token = self._previous()
            return ast.ContinueStatement(continue_token.location)

        is_print_statement = (
            self._check(TokenType.IDENTIFIER) and self._peek().lexeme == "print"
        )
        if is_print_statement:
            print_token = self._advance()
            value_to_print = self._parse_expression()
            return ast.PrintStatement(print_token.location, value_to_print)

        expression = self._parse_expression()

        if self._match(TokenType.DO):
            expression = self._attach_do_block(expression, self._previous())

        return ast.ExpressionStatement(expression.location, expression)

    def _parse_public_definition(self) -> ast.Statement:
        if self._match(TokenType.FUNCTION):
            return self._parse_function_definition(self._previous(), is_public=True)
        if self._match(TokenType.STRUCT):
            return self._parse_struct_definition(self._previous(), is_public=True)

        raise ParserError(
            self._peek().location,
            "`pub` can only expose a function or struct from its package.",
            expected="`fn` or `struct`",
            found=self._peek().describe(),
        )

    def _parse_function_definition(
        self,
        function_token: Token,
        *,
        is_public: bool,
    ) -> ast.FunctionDefinition:
        name_token = self._consume(
            TokenType.IDENTIFIER,
            "Every function needs a name after `fn`.",
            "a snake_case function name",
        )
        validate_function_name(name_token.lexeme, name_token.location)

        parameters: list[ast.FunctionParameterDefinition] = []
        if self._match(TokenType.LEFT_PARENTHESIS):
            parameters = self._parse_function_parameters(name_token.lexeme)
            self._consume(
                TokenType.RIGHT_PARENTHESIS,
                f"The parameter list for `{name_token.lexeme}` is not closed.",
                "`)`",
            )
        elif not self._check(TokenType.NEWLINE):
            raise ParserError(
                self._peek().location,
                f"Function `{name_token.lexeme}` must put its parameters in parentheses.",
                expected="`(` or the end of the line for a parameterless function",
                found=self._peek().describe(),
            )

        if self._match(TokenType.ASSIGN):
            result_expression = self._parse_expression()
            body = [
                ast.ReturnStatement(
                    result_expression.location,
                    result_expression,
                )
            ]
            return ast.FunctionDefinition(
                function_token.location,
                name_token.lexeme,
                parameters,
                body,
                is_public,
            )

        self._require_line_after_header("function definition")
        body = self._parse_block_until(lambda: self._check(TokenType.END))
        self._consume(TokenType.END, "This function is missing its closing `end`.", "`end`")
        self._validate_function_returns(name_token, body)

        return ast.FunctionDefinition(
            function_token.location,
            name_token.lexeme,
            parameters,
            body,
            is_public,
        )

    def _parse_function_parameters(
        self,
        function_name: str,
    ) -> list[ast.FunctionParameterDefinition]:
        """Parse positional parameters first, followed by named parameters.

        The four forms map directly to two independent facts:

        * ``name`` is required and positional.
        * ``name=default`` is optional and positional.
        * ``name:`` is required and named.
        * ``name: = default`` is optional and named.

        Keeping those facts explicit avoids a compact marker encoding that every
        later reader would have to memorize.
        """

        parameters: list[ast.FunctionParameterDefinition] = []
        parameter_names: set[str] = set()
        has_seen_named_parameter = False
        has_seen_optional_positional_parameter = False
        self._skip_newlines()

        while not self._check(TokenType.RIGHT_PARENTHESIS):
            parameter_token = self._consume(
                TokenType.IDENTIFIER,
                "Function parameters must be variable names.",
                "a snake_case parameter name",
            )
            validate_variable_name(parameter_token.lexeme, parameter_token.location)
            if parameter_token.lexeme in parameter_names:
                raise ParserError(
                    parameter_token.location,
                    f"Function `{function_name}` declares `{parameter_token.lexeme}` more than once.",
                    expected="a unique parameter name",
                    found=parameter_token.lexeme,
                )
            parameter_names.add(parameter_token.lexeme)

            is_named_parameter = self._match(TokenType.COLON)
            if is_named_parameter:
                has_seen_named_parameter = True
            elif has_seen_named_parameter:
                raise ParserError(
                    parameter_token.location,
                    "Positional parameters must appear before named parameters.",
                    expected="a named parameter such as `age:`",
                    found=parameter_token.lexeme,
                )

            default_value = None
            if self._match(TokenType.ASSIGN):
                default_value = self._parse_expression()

            is_optional_positional = not is_named_parameter and default_value is not None
            is_required_positional = not is_named_parameter and default_value is None
            if is_required_positional and has_seen_optional_positional_parameter:
                raise ParserError(
                    parameter_token.location,
                    "A required positional parameter cannot follow an optional one.",
                    expected="required positional parameters before parameters with defaults",
                    found=parameter_token.lexeme,
                )
            if is_optional_positional:
                has_seen_optional_positional_parameter = True

            parameters.append(
                ast.FunctionParameterDefinition(
                    parameter_token.lexeme,
                    parameter_token.location,
                    is_named_parameter,
                    default_value,
                )
            )

            self._skip_newlines()
            if not self._match(TokenType.COMMA):
                break
            self._skip_newlines()
            if self._check(TokenType.RIGHT_PARENTHESIS):
                break

        return parameters

    def _parse_struct_definition(
        self,
        struct_token: Token,
        *,
        is_public: bool,
    ) -> ast.StructDefinition:
        name_token = self._consume(
            TokenType.IDENTIFIER,
            "Every struct needs a name after `struct`.",
            "a PascalCase struct name",
        )
        validate_struct_name(name_token.lexeme, name_token.location)

        fields: list[ast.StructFieldDefinition] = []
        field_names: set[str] = set()
        self._skip_newlines()
        while not self._check(TokenType.END) and not self._is_at_end():
            field_token = self._consume(
                TokenType.IDENTIFIER,
                f"The body of `{name_token.lexeme}` may only contain field declarations.",
                "a snake_case field name or `end`",
            )
            validate_field_name(field_token.lexeme, field_token.location)
            if field_token.lexeme in field_names:
                raise ParserError(
                    field_token.location,
                    f"Struct `{name_token.lexeme}` declares `{field_token.lexeme}` more than once.",
                    expected="a unique field name",
                    found=field_token.lexeme,
                )
            field_names.add(field_token.lexeme)

            default_value = None
            if self._match(TokenType.ASSIGN):
                default_value = self._parse_expression()

            fields.append(ast.StructFieldDefinition(field_token.lexeme, field_token.location, default_value))

            if self._match(TokenType.COMMA):
                self._skip_newlines()
                continue

            if self._match(TokenType.NEWLINE):
                self._skip_newlines()
                if self._check(TokenType.END):
                    break
                raise ParserError(
                    self._peek().location,
                    "Struct fields must be separated by commas.",
                    expected="`,` after the previous field",
                    found=self._peek().describe(),
                )

            if not self._check(TokenType.END):
                raise ParserError(
                    self._peek().location,
                    "Struct fields must be separated by commas.",
                    expected="`,` or `end`",
                    found=self._peek().describe(),
                )

        self._consume(TokenType.END, "This struct is missing its closing `end`.", "`end`")
        return ast.StructDefinition(
            struct_token.location,
            name_token.lexeme,
            fields,
            is_public,
        )

    def _parse_package_header(self) -> str:
        name_token = self._consume(
            TokenType.IDENTIFIER,
            "Every package file needs a PascalCase name after `package`.",
            "a PascalCase package name",
        )
        validate_package_name(name_token.lexeme, name_token.location)

        self._require_line_after_header("package declaration")
        return name_token.lexeme

    def _validate_package_contains_declarations_only(
        self,
        package_statements: list[ast.Statement],
    ) -> None:
        """Keep loading inert so imports never perform application actions.

        A package answers “what exists?” and loading it must not perform an
        application action. These are definitions:

        * ``MAX_RETRIES = 5`` names a constant.
        * ``struct User ... end`` describes data.
        * ``fn find_user() ... end`` describes behavior for later use.

        In contrast, ``user = User()`` creates runtime state and ``print user``
        performs I/O. Rejecting the whole file during parsing prevents earlier
        definitions from being installed before the invalid action is found.
        """

        for statement in package_statements:
            if self._is_package_constant_declaration(statement):
                constant_expression = statement.expression
                if self._is_inert_constant_value(constant_expression.value):
                    continue
                raise PackageContentError(
                    constant_expression.value.location,
                    "Package constants cannot execute code while their package loads.",
                    expected="an inert literal, list, range, or arithmetic expression",
                    found="a value that reads a name or calls a function",
                )

            if self._is_allowed_package_declaration(statement):
                continue

            raise PackageContentError(
                statement.location,
                "Runtime statement found at package level.\n\n"
                "Packages can only contain:\n"
                "    import\n"
                "    constant\n"
                "    struct\n"
                "    function\n\n"
                "Move this code inside a function.",
            )

    @staticmethod
    def _is_allowed_package_declaration(statement: ast.Statement) -> bool:
        if isinstance(
            statement,
            (ast.ImportStatement, ast.StructDefinition, ast.FunctionDefinition),
        ):
            return True

        if not isinstance(statement, ast.ExpressionStatement):
            return False
        if not isinstance(statement.expression, ast.AssignmentExpression):
            return False

        assignment_target = statement.expression.target
        if not isinstance(assignment_target, ast.VariableExpression):
            return False

        return CONSTANT_CASE_PATTERN.fullmatch(assignment_target.name) is not None

    @staticmethod
    def _is_package_constant_declaration(statement: ast.Statement) -> bool:
        if not isinstance(statement, ast.ExpressionStatement):
            return False
        expression = statement.expression
        if not isinstance(expression, ast.AssignmentExpression):
            return False
        if not isinstance(expression.target, ast.VariableExpression):
            return False
        return CONSTANT_CASE_PATTERN.fullmatch(expression.target.name) is not None

    @classmethod
    def _is_inert_constant_value(cls, expression: ast.Expression) -> bool:
        if isinstance(expression, ast.LiteralExpression):
            if not isinstance(expression.value, str):
                return True
            return not cls._string_contains_interpolation(expression.value)
        if isinstance(expression, ast.UnaryExpression):
            return cls._is_inert_constant_value(expression.operand)
        if isinstance(expression, ast.BinaryExpression):
            return (
                cls._is_inert_constant_value(expression.left_operand)
                and cls._is_inert_constant_value(expression.right_operand)
            )
        if isinstance(expression, ast.ListExpression):
            return all(cls._is_inert_constant_value(item) for item in expression.items)
        if isinstance(expression, ast.RangeExpression):
            return (
                cls._is_inert_constant_value(expression.first_value)
                and cls._is_inert_constant_value(expression.last_value)
            )
        return False

    @staticmethod
    def _string_contains_interpolation(value: str) -> bool:
        current_index = 0
        while current_index < len(value):
            current_character = value[current_index]
            next_character = (
                value[current_index + 1]
                if current_index + 1 < len(value)
                else ""
            )
            if current_character == "{" and next_character == "{":
                current_index += 2
                continue
            if current_character == "}" and next_character == "}":
                current_index += 2
                continue
            if current_character == "{" or current_character == "}":
                return True
            current_index += 1
        return False

    def _parse_import(self, import_token: Token) -> ast.ImportStatement:
        first_segment = self._consume(
            TokenType.IDENTIFIER,
            "`import` must be followed by a package path.",
            "a snake_case path such as `billing/accounts`",
        )
        validate_package_path_segment(first_segment.lexeme, first_segment.location)
        path_tokens = [first_segment]

        while self._match(TokenType.SLASH):
            slash_token = self._previous()
            previous_segment = path_tokens[-1]
            segment_token = self._consume(
                TokenType.IDENTIFIER,
                "A package-path slash must be followed by another name.",
                "a snake_case path segment",
            )
            self._require_connected_package_path(
                previous_segment,
                slash_token,
                segment_token,
            )
            validate_package_path_segment(segment_token.lexeme, segment_token.location)
            path_tokens.append(segment_token)

        alias = None
        selected_names: list[str] = []

        if self._match(TokenType.AS):
            alias_token = self._consume(
                TokenType.IDENTIFIER,
                "An import alias needs a name after `as`.",
                "an alias name",
            )
            alias = alias_token.lexeme
            validate_package_name(alias, alias_token.location)

        elif self._match(TokenType.COLON):
            self._require_line_after_header("selected import")
            self._skip_newlines()

            # A trailing comma tells the parser another selected name follows.
            # This avoids assigning semantic meaning to indentation. For example:
            #
            #     import text:
            #         trim,
            #         lowercase
            #
            # ``lowercase`` has no comma, so the following line begins a normal
            # statement even if both lines happen to use the same indentation.
            while True:
                selected_token = self._consume(
                    TokenType.IDENTIFIER,
                    "A selected import must name a package member.",
                    "a function, struct, or constant name",
                )
                selected_names.append(selected_token.lexeme)

                if not self._match(TokenType.COMMA):
                    break
                self._skip_newlines()

        return ast.ImportStatement(
            import_token.location,
            "/".join(path_token.lexeme for path_token in path_tokens),
            alias,
            selected_names,
        )

    @staticmethod
    def _require_connected_package_path(
        previous_segment: Token,
        slash_token: Token,
        next_segment: Token,
    ) -> None:
        slash_follows_segment = (
            slash_token.location.line == previous_segment.location.line
            and slash_token.location.column
            == previous_segment.location.column + len(previous_segment.lexeme)
        )
        segment_follows_slash = (
            next_segment.location.line == slash_token.location.line
            and next_segment.location.column == slash_token.location.column + 1
        )
        if slash_follows_segment and segment_follows_slash:
            return

        raise ParserError(
            slash_token.location,
            "Package import paths cannot contain whitespace around `/`.",
            expected="a connected path such as `billing/accounts`",
            found=(
                f"{previous_segment.lexeme} / {next_segment.lexeme}"
            ),
        )

    def _parse_if_statement(self, if_token: Token) -> ast.IfStatement:
        first_condition = self._parse_expression()
        self._require_line_after_header("if condition")
        first_body = self._parse_block_until(
            lambda: self._check_any(TokenType.ELSIF, TokenType.ELSE, TokenType.END)
        )
        branches = [ast.ConditionalBranch(first_condition, first_body)]

        while self._match(TokenType.ELSIF):
            branch_condition = self._parse_expression()
            self._require_line_after_header("elsif condition")
            branch_body = self._parse_block_until(
                lambda: self._check_any(TokenType.ELSIF, TokenType.ELSE, TokenType.END)
            )
            branches.append(ast.ConditionalBranch(branch_condition, branch_body))

        else_body = None
        if self._match(TokenType.ELSE):
            self._require_line_after_header("else")
            else_body = self._parse_block_until(lambda: self._check(TokenType.END))

        self._consume(TokenType.END, "This `if` expression is missing its closing `end`.", "`end`")
        return ast.IfStatement(if_token.location, branches, else_body)

    def _parse_for_statement(self, for_token: Token) -> ast.ForStatement:
        item_token = self._consume(
            TokenType.IDENTIFIER,
            "A `for` loop needs a variable for its current item.",
            "a snake_case variable name",
        )
        validate_variable_name(item_token.lexeme, item_token.location)
        self._consume(
            TokenType.IN,
            "The loop variable must be followed by `in`.",
            "`in`",
        )
        iterable_expression = self._parse_expression()
        self._require_line_after_header("for loop")
        body = self._parse_block_until(lambda: self._check(TokenType.END))
        self._consume(TokenType.END, "This `for` loop is missing its closing `end`.", "`end`")
        return ast.ForStatement(
            for_token.location,
            item_token.lexeme,
            iterable_expression,
            body,
        )

    def _parse_when_expression(self, when_token: Token) -> ast.WhenExpression:
        matched_expression = self._parse_expression()
        self._require_line_after_header("when expression")
        branches: list[ast.WhenBranch] = []
        self._skip_newlines()
        pattern_column: int | None = None

        while not self._check(TokenType.END) and not self._is_at_end():
            if pattern_column is None:
                pattern_column = self._peek().location.column
            pattern = self._parse_when_pattern()
            binding_name = self._parse_when_binding()
            self._require_line_after_header("when pattern")
            branch_body = self._parse_block_until(
                lambda: self._starts_when_pattern_or_end(pattern_column)
            )
            if not branch_body:
                raise ParserError(
                    pattern.location,
                    "A `when` branch needs a body.",
                    expected="at least one statement below the pattern",
                    found="an empty branch",
                )
            branches.append(ast.WhenBranch(pattern, binding_name, branch_body))

        self._consume(
            TokenType.END,
            "This `when` expression is missing its closing `end`.",
            "`end`",
        )
        has_fallback = branches and isinstance(
            branches[-1].pattern,
            ast.WildcardPattern,
        )
        if not has_fallback:
            raise ParserError(
                when_token.location,
                "Every `when` expression needs a final `_` branch.",
                expected="`_` as the final pattern",
                found="a `when` expression without a fallback",
            )
        return ast.WhenExpression(when_token.location, matched_expression, branches)

    def _parse_when_binding(self) -> str | None:
        if not self._match(TokenType.AS):
            return None

        binding_token = self._consume(
            TokenType.IDENTIFIER,
            "`as` must be followed by a local binding name.",
            "a snake_case variable name",
        )
        validate_variable_name(binding_token.lexeme, binding_token.location)
        return binding_token.lexeme

    def _parse_when_pattern(self) -> ast.WhenPattern:
        if self._match(TokenType.NIL):
            return ast.NilPattern(self._previous().location)
        if self._match(TokenType.WILDCARD):
            return ast.WildcardPattern(self._previous().location)
        if self._match(TokenType.STRING, TokenType.NUMBER):
            literal_token = self._previous()
            return ast.LiteralPattern(literal_token.literal, literal_token.location)
        if self._match(TokenType.TRUE):
            return ast.LiteralPattern(True, self._previous().location)
        if self._match(TokenType.FALSE):
            return ast.LiteralPattern(False, self._previous().location)
        if self._check(TokenType.IDENTIFIER):
            name_tokens = self._parse_dotted_name(
                "A struct pattern must contain a struct name."
            )
            for package_token in name_tokens[:-1]:
                validate_package_name(package_token.lexeme, package_token.location)
            struct_token = name_tokens[-1]
            validate_struct_name(struct_token.lexeme, struct_token.location)
            return ast.StructPattern(
                [name_token.lexeme for name_token in name_tokens],
                name_tokens[0].location,
            )

        raise ParserError(
            self._peek().location,
            "A `when` branch must begin with a struct, literal, `nil`, or `_`.",
            expected="a pattern such as `Accounts.User`, `\"Guwahati\"`, `nil`, or `_`",
            found=self._peek().describe(),
        )

    def _starts_when_pattern_or_end(self, pattern_column: int) -> bool:
        if self._check(TokenType.END):
            return True
        if self._peek().location.column != pattern_column:
            return False

        single_token_patterns = {
            TokenType.NIL,
            TokenType.WILDCARD,
            TokenType.STRING,
            TokenType.NUMBER,
            TokenType.TRUE,
            TokenType.FALSE,
        }
        token_index = self.current_index
        if self.tokens[token_index].token_type in single_token_patterns:
            token_index += 1
        elif self.tokens[token_index].token_type is TokenType.IDENTIFIER:
            token_index = self._when_struct_pattern_end(token_index)
            if token_index == self.current_index:
                return False
        else:
            return False

        if self.tokens[token_index].token_type is TokenType.AS:
            token_index += 1
            if self.tokens[token_index].token_type is not TokenType.IDENTIFIER:
                return False
            token_index += 1

        return self.tokens[token_index].token_type is TokenType.NEWLINE

    def _when_struct_pattern_end(self, token_index: int) -> int:

        # A qualified type pattern is an alternating sequence such as
        # ``Accounts . User`` that occupies its whole line. Checking the token
        # sequence here avoids mistaking ``Accounts.find_user()`` in a branch
        # body for the beginning of the next pattern.
        expects_identifier = True
        while token_index < len(self.tokens):
            token = self.tokens[token_index]
            if expects_identifier and token.token_type is TokenType.IDENTIFIER:
                if PASCAL_CASE_PATTERN.fullmatch(token.lexeme) is None:
                    return self.current_index
                expects_identifier = False
                token_index += 1
                continue
            if not expects_identifier and token.token_type is TokenType.DOT:
                expects_identifier = True
                token_index += 1
                continue
            break

        return token_index if not expects_identifier else self.current_index

    def _parse_ignore_statement(self, ignore_token: Token) -> ast.IgnoreStatement:
        expression = self._parse_expression()
        if not isinstance(expression, ast.CallExpression):
            raise ParserError(
                expression.location,
                "`ignore` must be followed by a function call.",
                expected="a fallible call such as `ignore save_user!()`",
                found=type(expression).__name__,
            )
        return ast.IgnoreStatement(ignore_token.location, expression)

    def _parse_return_statement(self, return_token: Token) -> ast.ReturnStatement:
        return_has_no_value = self._check_any(
            TokenType.NEWLINE,
            TokenType.END_OF_FILE,
            TokenType.END,
        )
        return_value = None if return_has_no_value else self._parse_expression()
        return ast.ReturnStatement(return_token.location, return_value)

    def _attach_do_block(
        self,
        expression: ast.Expression,
        do_token: Token,
    ) -> ast.CallExpression:
        if not isinstance(expression, ast.CallExpression):
            raise ParserError(
                do_token.location,
                "A `do` block must follow a function call so it has a receiver.",
                expected="a call such as `Database.transaction do`",
                found="`do` after a non-call expression",
            )

        self._require_line_after_header("do block")
        block_body = self._parse_block_until(lambda: self._check(TokenType.END))
        self._consume(TokenType.END, "This `do` block is missing its closing `end`.", "`end`")
        expression.arguments.append(
            ast.CallArgument(ast.BlockExpression(do_token.location, block_body))
        )
        return expression

    def _parse_block_until(self, reached_end: Callable[[], bool]) -> list[ast.Statement]:
        statements: list[ast.Statement] = []
        self._skip_newlines()

        while not reached_end() and not self._is_at_end():
            statements.append(self._parse_statement())
            self._finish_statement()
            self._skip_newlines()

        return statements

    def _parse_expression(self) -> ast.Expression:
        # Each method below owns one precedence level. Consider ``2 + 3 * 4``:
        # ``_parse_term`` reads the ``+``, but asks ``_parse_factor`` for its
        # right-hand side. The factor method consumes ``3 * 4`` as one subtree,
        # giving the AST ``2 + (3 * 4)`` without a precedence table or backtracking.
        return self._parse_assignment()

    def _parse_assignment(
        self,
        *,
        allow_inline_when: bool = True,
    ) -> ast.Expression:
        assignment_target = self._parse_range()
        if not self._match(TokenType.ASSIGN):
            expression = self._parse_parenthesis_free_call(assignment_target)
            if allow_inline_when:
                return self._parse_inline_when(expression)
            return expression

        assignment_operator = self._previous()
        assigned_value = self._parse_assignment()
        is_valid_target = isinstance(
            assignment_target,
            (ast.VariableExpression, ast.FieldAccessExpression),
        )
        if not is_valid_target:
            raise ParserError(
                assignment_operator.location,
                "Only a variable or struct field can appear to the left of `=`.",
                expected="a target such as `name` or `user.name`",
                found="a computed expression",
            )

        if isinstance(assignment_target, ast.VariableExpression):
            validate_variable_name(assignment_target.name, assignment_target.location)

        return ast.AssignmentExpression(
            assignment_operator.location,
            assignment_target,
            assigned_value,
        )

    def _parse_inline_when(
        self,
        matched_expression: ast.Expression,
    ) -> ast.Expression:
        """Parse ``value when Pattern`` with an optional one-line fallback.

        This is the compact form of the existing exhaustive ``when``. The
        matched expression is stored separately so the interpreter can both
        test and preserve its value without evaluating a fallible call twice.
        """

        if not self._match(TokenType.WHEN):
            return matched_expression

        when_token = self._previous()
        pattern = self._parse_when_pattern()
        if isinstance(pattern, ast.WildcardPattern):
            raise ParserError(
                pattern.location,
                "An inline `when` wildcard would always preserve the original value.",
                expected="a meaningful struct, literal, or `nil` pattern",
                found="`_`",
            )

        fallback_expression = None
        if self._match(TokenType.ELSE):
            fallback_expression = self._parse_assignment()

        return ast.InlineWhenExpression(
            when_token.location,
            matched_expression,
            pattern,
            fallback_expression,
        )

    def _parse_range(self) -> ast.Expression:
        first_value = self._parse_equality()
        if not self._match(TokenType.RANGE):
            return first_value

        range_operator = self._previous()
        last_value = self._parse_equality()
        return ast.RangeExpression(
            range_operator.location,
            first_value,
            last_value,
        )

    def _parse_parenthesis_free_call(
        self,
        callable_expression: ast.Expression,
    ) -> ast.Expression:
        """Parse an unambiguous same-line call such as ``greet "Hirak"``.

        The call must contain at least one argument; ``greet`` alone remains a
        reference to the function value. Arguments cannot continue after a
        newline without parentheses. These two constraints keep variables and
        the next statement from being silently consumed as part of a call.
        """

        if not isinstance(
            callable_expression,
            (ast.VariableExpression, ast.FieldAccessExpression),
        ):
            return callable_expression
        if self._check(TokenType.WHEN):
            # ``result when User`` is an inline pattern filter, not a call to
            # ``result`` with a block ``when`` expression as its argument.
            # A full ``when`` passed as an argument remains available through
            # an explicit parenthesized call.
            return callable_expression
        if not self._token_can_start_expression(self._peek()):
            return callable_expression

        arguments: list[ast.CallArgument] = []
        encountered_named_argument = False
        while True:
            argument_name = None
            begins_named_argument = (
                self._check(TokenType.IDENTIFIER)
                and self._peek_next().token_type is TokenType.ASSIGN
            )
            if begins_named_argument:
                argument_token = self._advance()
                argument_name = argument_token.lexeme
                validate_variable_name(argument_name, argument_token.location)
                self._advance()
                encountered_named_argument = True
            elif encountered_named_argument:
                raise ParserError(
                    self._peek().location,
                    "A positional argument cannot follow a named argument.",
                    expected="all positional arguments before named arguments",
                    found=self._peek().describe(),
                )

            # Leave a trailing ``when Pattern`` for the complete call. Without
            # this boundary, ``find_user! 10 when User`` would filter the
            # argument ``10`` instead of the result of ``find_user! 10``.
            argument_value = self._parse_assignment(allow_inline_when=False)
            arguments.append(ast.CallArgument(argument_value, argument_name))
            if not self._match(TokenType.COMMA):
                break
            if not self._token_can_start_expression(self._peek()):
                raise ParserError(
                    self._peek().location,
                    "A parenthesis-free call cannot continue onto another line.",
                    expected="another argument on the same line",
                    found=self._peek().describe(),
                )

        return ast.CallExpression(
            callable_expression.location,
            callable_expression,
            arguments,
            uses_parentheses=False,
        )

    @staticmethod
    def _token_can_start_expression(token: Token) -> bool:
        return token.token_type in {
            TokenType.FALSE,
            TokenType.TRUE,
            TokenType.NIL,
            TokenType.NUMBER,
            TokenType.STRING,
            TokenType.IDENTIFIER,
            TokenType.LEFT_PARENTHESIS,
            TokenType.LEFT_BRACKET,
            TokenType.MINUS,
            TokenType.WHEN,
        }

    def _parse_equality(self) -> ast.Expression:
        expression = self._parse_comparison()
        while self._match(TokenType.EQUAL, TokenType.NOT_EQUAL):
            operator = self._previous()
            right_operand = self._parse_comparison()
            expression = ast.BinaryExpression(
                operator.location,
                expression,
                operator.lexeme,
                right_operand,
            )
        return expression

    def _parse_comparison(self) -> ast.Expression:
        expression = self._parse_term()
        while self._match(
            TokenType.GREATER,
            TokenType.GREATER_EQUAL,
            TokenType.LESS,
            TokenType.LESS_EQUAL,
        ):
            operator = self._previous()
            right_operand = self._parse_term()
            expression = ast.BinaryExpression(
                operator.location,
                expression,
                operator.lexeme,
                right_operand,
            )
        return expression

    def _parse_term(self) -> ast.Expression:
        expression = self._parse_factor()
        while self._match(TokenType.PLUS, TokenType.MINUS):
            operator = self._previous()
            right_operand = self._parse_factor()
            expression = ast.BinaryExpression(
                operator.location,
                expression,
                operator.lexeme,
                right_operand,
            )
        return expression

    def _parse_factor(self) -> ast.Expression:
        expression = self._parse_unary()
        while self._match(TokenType.STAR, TokenType.SLASH):
            operator = self._previous()
            right_operand = self._parse_unary()
            expression = ast.BinaryExpression(
                operator.location,
                expression,
                operator.lexeme,
                right_operand,
            )
        return expression

    def _parse_unary(self) -> ast.Expression:
        if self._match(TokenType.MINUS):
            operator = self._previous()
            operand = self._parse_unary()
            return ast.UnaryExpression(operator.location, operator.lexeme, operand)
        return self._parse_call_and_field_access()

    def _parse_call_and_field_access(self) -> ast.Expression:
        expression = self._parse_primary()

        while True:
            if self._match(TokenType.LEFT_PARENTHESIS):
                expression = self._finish_call(expression, self._previous())
                continue

            if self._match(TokenType.DOT):
                field_token = self._consume(
                    TokenType.IDENTIFIER,
                    "A dot must be followed by a field or package member name.",
                    "a name after `.`",
                )
                expression = ast.FieldAccessExpression(
                    field_token.location,
                    expression,
                    field_token.lexeme,
                )
                continue

            break

        return expression

    def _finish_call(
        self,
        callable_expression: ast.Expression,
        opening_parenthesis: Token,
    ) -> ast.CallExpression:
        arguments: list[ast.CallArgument] = []
        self._skip_newlines()

        if not self._check(TokenType.RIGHT_PARENTHESIS):
            while True:
                argument_name = None
                begins_named_argument = (
                    self._check(TokenType.IDENTIFIER)
                    and self._peek_next().token_type is TokenType.ASSIGN
                )
                if begins_named_argument:
                    argument_name = self._advance().lexeme
                    validate_variable_name(argument_name, self._previous().location)
                    self._advance()  # The lookahead above already proved this is `=`.

                argument_value = self._parse_expression()
                arguments.append(ast.CallArgument(argument_value, argument_name))
                self._skip_newlines()

                if not self._match(TokenType.COMMA):
                    break
                self._skip_newlines()
                if self._check(TokenType.RIGHT_PARENTHESIS):
                    break

        self._consume(
            TokenType.RIGHT_PARENTHESIS,
            "This function or struct call is missing its closing parenthesis.",
            "`)`",
        )
        return ast.CallExpression(opening_parenthesis.location, callable_expression, arguments)

    def _parse_primary(self) -> ast.Expression:
        if self._match(TokenType.WHEN):
            return self._parse_when_expression(self._previous())
        if self._match(TokenType.FALSE):
            return ast.LiteralExpression(self._previous().location, False)
        if self._match(TokenType.TRUE):
            return ast.LiteralExpression(self._previous().location, True)
        if self._match(TokenType.NIL):
            return ast.LiteralExpression(self._previous().location, None)
        if self._match(TokenType.NUMBER, TokenType.STRING):
            literal_token = self._previous()
            return ast.LiteralExpression(literal_token.location, literal_token.literal)
        if self._match(TokenType.IDENTIFIER):
            identifier_token = self._previous()
            return ast.VariableExpression(identifier_token.location, identifier_token.lexeme)
        if self._match(TokenType.LEFT_BRACKET):
            return self._parse_list_expression(self._previous())
        if self._match(TokenType.LEFT_PARENTHESIS):
            opening_parenthesis = self._previous()
            expression = self._parse_expression()
            self._consume(
                TokenType.RIGHT_PARENTHESIS,
                "This grouped expression is missing its closing parenthesis.",
                "`)`",
            )
            return expression

        raise ParserError(
            self._peek().location,
            "An expression must start with a value, name, or opening parenthesis.",
            expected="an expression",
            found=self._peek().describe(),
        )

    def _parse_list_expression(self, opening_bracket: Token) -> ast.ListExpression:
        items: list[ast.Expression] = []
        self._skip_newlines()

        while not self._check(TokenType.RIGHT_BRACKET):
            items.append(self._parse_expression())
            self._skip_newlines()

            if not self._match(TokenType.COMMA):
                break
            self._skip_newlines()
            if self._check(TokenType.RIGHT_BRACKET):
                break

        self._consume(
            TokenType.RIGHT_BRACKET,
            "This list is missing its closing bracket.",
            "`]`",
        )
        return ast.ListExpression(opening_bracket.location, items)

    def _validate_function_returns(
        self,
        name_token: Token,
        body: list[ast.Statement],
    ) -> None:
        outcomes = self._block_outcomes(body)
        returns_a_value = "value" in outcomes
        every_path_returns_a_value = outcomes == {"value"}
        if not returns_a_value or every_path_returns_a_value:
            return

        raise ParserError(
            name_token.location,
            f"Function `{name_token.lexeme}` returns a value on only some paths.",
            expected="an explicit `return value` on every completion path",
            found="a path that reaches `end` or uses bare `return`",
        )

    def _validate_unique_function_names(
        self,
        statements: list[ast.Statement],
    ) -> None:
        definitions_by_name: dict[str, ast.FunctionDefinition] = {}
        for statement in statements:
            if isinstance(statement, ast.FunctionDefinition):
                existing_definition = definitions_by_name.get(statement.name)
                if existing_definition is not None:
                    raise ParserError(
                        statement.location,
                        f"Function `{statement.name}` is already defined in this scope.",
                        expected="one definition for each function name",
                        found=f"another definition of `{statement.name}`",
                    )
                definitions_by_name[statement.name] = statement
                self._validate_unique_function_names(statement.body)
                continue

            if isinstance(statement, ast.IfStatement):
                for branch in statement.branches:
                    self._validate_unique_function_names(branch.body)
                if statement.else_body is not None:
                    self._validate_unique_function_names(statement.else_body)
            elif isinstance(statement, ast.ForStatement):
                self._validate_unique_function_names(statement.body)
            elif isinstance(statement, ast.ExpressionStatement):
                self._validate_functions_in_expression(statement.expression)
            elif isinstance(statement, ast.PrintStatement):
                self._validate_functions_in_expression(statement.expression)
            elif isinstance(statement, ast.IgnoreStatement):
                self._validate_functions_in_expression(statement.expression)

    def _validate_functions_in_expression(self, expression: ast.Expression) -> None:
        if isinstance(expression, ast.WhenExpression):
            for branch in expression.branches:
                self._validate_unique_function_names(branch.body)
            self._validate_functions_in_expression(expression.matched_expression)
            return

        if isinstance(expression, ast.InlineWhenExpression):
            self._validate_functions_in_expression(expression.matched_expression)
            if expression.fallback_expression is not None:
                self._validate_functions_in_expression(expression.fallback_expression)
            return

        if isinstance(expression, ast.BlockExpression):
            self._validate_unique_function_names(expression.statements)
            return

        child_expressions: list[ast.Expression] = []
        if isinstance(expression, ast.UnaryExpression):
            child_expressions = [expression.operand]
        elif isinstance(expression, ast.BinaryExpression):
            child_expressions = [expression.left_operand, expression.right_operand]
        elif isinstance(expression, ast.AssignmentExpression):
            child_expressions = [expression.value, expression.target]
        elif isinstance(expression, ast.CallExpression):
            child_expressions = [expression.callable_expression]
            child_expressions.extend(argument.value for argument in expression.arguments)
        elif isinstance(expression, ast.FieldAccessExpression):
            child_expressions = [expression.target]
        elif isinstance(expression, ast.ListExpression):
            child_expressions = expression.items
        elif isinstance(expression, ast.RangeExpression):
            child_expressions = [expression.first_value, expression.last_value]

        for child_expression in child_expressions:
            self._validate_functions_in_expression(child_expression)

    def _block_outcomes(self, statements: list[ast.Statement]) -> set[str]:
        outcomes = {"continue"}
        for statement in statements:
            if "continue" not in outcomes:
                break
            outcomes.remove("continue")
            outcomes.update(self._statement_outcomes(statement))
        return outcomes

    def _statement_outcomes(self, statement: ast.Statement) -> set[str]:
        if isinstance(statement, ast.ReturnStatement):
            if statement.expression is None:
                return {"nil"}

            expression_outcomes = self._expression_outcomes(statement.expression)
            outcomes = expression_outcomes - {"continue"}
            if "continue" in expression_outcomes:
                outcomes.add("value")
            return outcomes

        if isinstance(statement, ast.IfStatement):
            outcomes: set[str] = set()
            for branch in statement.branches:
                outcomes.update(self._block_outcomes(branch.body))
            if statement.else_body is None:
                outcomes.add("continue")
            else:
                outcomes.update(self._block_outcomes(statement.else_body))
            return outcomes

        if isinstance(statement, ast.ForStatement):
            return {"continue"} | (self._block_outcomes(statement.body) - {"continue"})

        if isinstance(statement, ast.ExpressionStatement):
            return self._expression_outcomes(statement.expression)
        if isinstance(statement, ast.PrintStatement):
            return self._expression_outcomes(statement.expression)
        if isinstance(statement, ast.IgnoreStatement):
            return self._expression_outcomes(statement.expression)

        return {"continue"}

    def _expression_outcomes(self, expression: ast.Expression) -> set[str]:
        if isinstance(expression, ast.WhenExpression):
            outcomes: set[str] = set()
            matched_outcomes = self._expression_outcomes(expression.matched_expression)
            outcomes.update(matched_outcomes - {"continue"})
            if "continue" in matched_outcomes:
                for branch in expression.branches:
                    outcomes.update(self._block_outcomes(branch.body))
            return outcomes

        if isinstance(expression, ast.InlineWhenExpression):
            outcomes: set[str] = set()
            matched_outcomes = self._expression_outcomes(expression.matched_expression)
            outcomes.update(matched_outcomes - {"continue"})
            if "continue" not in matched_outcomes:
                return outcomes

            # A successful pattern preserves the matched value and continues.
            outcomes.add("continue")
            if expression.fallback_expression is not None:
                fallback_outcomes = self._expression_outcomes(
                    expression.fallback_expression
                )
                outcomes.update(fallback_outcomes - {"continue"})
            return outcomes

        child_expressions: list[ast.Expression] = []
        if isinstance(expression, ast.UnaryExpression):
            child_expressions = [expression.operand]
        elif isinstance(expression, ast.BinaryExpression):
            child_expressions = [expression.left_operand, expression.right_operand]
        elif isinstance(expression, ast.AssignmentExpression):
            child_expressions = [expression.value]
            if isinstance(expression.target, ast.FieldAccessExpression):
                child_expressions.append(expression.target.target)
        elif isinstance(expression, ast.CallExpression):
            child_expressions = [expression.callable_expression]
            child_expressions.extend(
                argument.value
                for argument in expression.arguments
                if not isinstance(argument.value, ast.BlockExpression)
            )
        elif isinstance(expression, ast.FieldAccessExpression):
            child_expressions = [expression.target]
        elif isinstance(expression, ast.ListExpression):
            child_expressions = expression.items
        elif isinstance(expression, ast.RangeExpression):
            child_expressions = [expression.first_value, expression.last_value]

        outcomes = {"continue"}
        for child_expression in child_expressions:
            if "continue" not in outcomes:
                break
            outcomes.remove("continue")
            outcomes.update(self._expression_outcomes(child_expression))
        return outcomes

    def _parse_dotted_name(self, explanation: str) -> list[Token]:
        first_name = self._consume(TokenType.IDENTIFIER, explanation, "a name")
        name_tokens = [first_name]
        while self._match(TokenType.DOT):
            name_tokens.append(
                self._consume(
                    TokenType.IDENTIFIER,
                    "A dot in a qualified name must be followed by another name.",
                    "a name after `.`",
                )
            )
        return name_tokens

    def _require_line_after_header(self, header_description: str) -> None:
        if self._match(TokenType.NEWLINE):
            self._skip_newlines()
            return

        raise ParserError(
            self._peek().location,
            f"The {header_description} must end before its body begins.",
            expected="the end of the line",
            found=self._peek().describe(),
        )

    def _finish_statement(self) -> None:
        if self._check_any(TokenType.NEWLINE, TokenType.END_OF_FILE):
            return

        # Block parsers intentionally leave their terminator for their caller.
        # Accepting it here permits compact empty bodies such as ``fn noop()\nend``
        # without teaching every statement parser about its enclosing construct.
        if self._check_any(TokenType.END, TokenType.ELSIF, TokenType.ELSE):
            return

        raise ParserError(
            self._peek().location,
            "Two expressions cannot share a line without a separator.",
            expected="the end of the line",
            found=self._peek().describe(),
        )

    def _skip_newlines(self) -> None:
        while self._match(TokenType.NEWLINE):
            pass

    def _match(self, *token_types: TokenType) -> bool:
        if not self._check_any(*token_types):
            return False
        self._advance()
        return True

    def _consume(
        self,
        token_type: TokenType,
        explanation: str,
        expected: str,
    ) -> Token:
        if self._check(token_type):
            return self._advance()

        raise ParserError(
            self._peek().location,
            explanation,
            expected=expected,
            found=self._peek().describe(),
        )

    def _check(self, token_type: TokenType) -> bool:
        return self._peek().token_type is token_type

    def _check_any(self, *token_types: TokenType) -> bool:
        return self._peek().token_type in token_types

    def _advance(self) -> Token:
        if not self._is_at_end():
            self.current_index += 1
        return self._previous()

    def _is_at_end(self) -> bool:
        return self._peek().token_type is TokenType.END_OF_FILE

    def _peek(self) -> Token:
        return self.tokens[self.current_index]

    def _peek_next(self) -> Token:
        next_index = min(self.current_index + 1, len(self.tokens) - 1)
        return self.tokens[next_index]

    def _previous(self) -> Token:
        return self.tokens[self.current_index - 1]
