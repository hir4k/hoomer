"""Recursive-descent parser for Hoomer's newline-oriented grammar."""

from __future__ import annotations

from collections.abc import Callable

from hoomer import ast
from hoomer.errors import ModuleContentError, ParserError
from hoomer.naming import (
    CONSTANT_CASE_PATTERN,
    PASCAL_CASE_PATTERN,
    validate_field_name,
    validate_function_name,
    validate_module_name,
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

        while not self._is_at_end():
            statements.append(self._parse_statement())
            self._finish_statement()
            self._skip_newlines()

        return ast.Program(statements)

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
        if self._match(TokenType.MODULE):
            return self._parse_module_definition(self._previous())
        if self._match(TokenType.IMPORT):
            return self._parse_import(self._previous())
        if self._match(TokenType.STRUCT):
            return self._parse_struct_definition(self._previous())
        if self._match(TokenType.FUNCTION):
            return self._parse_function_definition(self._previous())
        if self._match(TokenType.IF):
            return self._parse_if_statement(self._previous())
        if self._match(TokenType.WHEN):
            return self._parse_when_statement(self._previous())
        if self._match(TokenType.RETURN):
            return self._parse_return_statement(self._previous())

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

    def _parse_function_definition(
        self,
        function_token: Token,
    ) -> ast.FunctionDefinition:
        name_token = self._consume(
            TokenType.IDENTIFIER,
            "Every function needs a name after `fn`.",
            "a snake_case function name",
        )
        validate_function_name(name_token.lexeme, name_token.location)

        self._consume(
            TokenType.LEFT_PARENTHESIS,
            f"Function `{name_token.lexeme}` must put its parameters in parentheses.",
            "`(`",
        )

        parameter_names: list[str] = []
        if not self._check(TokenType.RIGHT_PARENTHESIS):
            while True:
                parameter_token = self._consume(
                    TokenType.IDENTIFIER,
                    "Function parameters must be variable names.",
                    "a snake_case parameter name",
                )
                validate_variable_name(parameter_token.lexeme, parameter_token.location)
                parameter_names.append(parameter_token.lexeme)
                if not self._match(TokenType.COMMA):
                    break

        self._consume(
            TokenType.RIGHT_PARENTHESIS,
            f"The parameter list for `{name_token.lexeme}` is not closed.",
            "`)`",
        )
        self._require_line_after_header("function definition")
        body = self._parse_block_until(lambda: self._check(TokenType.END))
        self._consume(TokenType.END, "This function is missing its closing `end`.", "`end`")

        return ast.FunctionDefinition(
            function_token.location,
            name_token.lexeme,
            parameter_names,
            body,
        )

    def _parse_struct_definition(
        self,
        struct_token: Token,
    ) -> ast.StructDefinition:
        name_token = self._consume(
            TokenType.IDENTIFIER,
            "Every struct needs a name after `struct`.",
            "a PascalCase struct name",
        )
        validate_struct_name(name_token.lexeme, name_token.location)
        self._require_line_after_header("struct definition")

        fields: list[ast.StructFieldDefinition] = []
        self._skip_newlines()
        while not self._check(TokenType.END) and not self._is_at_end():
            field_token = self._consume(
                TokenType.IDENTIFIER,
                f"The body of `{name_token.lexeme}` may only contain field declarations.",
                "a snake_case field name or `end`",
            )
            validate_field_name(field_token.lexeme, field_token.location)

            default_value = None
            if self._match(TokenType.ASSIGN):
                default_value = self._parse_expression()

            fields.append(ast.StructFieldDefinition(field_token.lexeme, field_token.location, default_value))
            self._finish_statement()
            self._skip_newlines()

        self._consume(TokenType.END, "This struct is missing its closing `end`.", "`end`")
        return ast.StructDefinition(
            struct_token.location,
            name_token.lexeme,
            fields,
        )

    def _parse_module_definition(
        self,
        module_token: Token,
    ) -> ast.ModuleDefinition:
        name_tokens = self._parse_dotted_name(
            "Every module needs a PascalCase name after `module`."
        )
        for name_token in name_tokens:
            validate_module_name(name_token.lexeme, name_token.location)

        self._require_line_after_header("module definition")
        body = self._parse_block_until(lambda: self._check(TokenType.END))
        self._consume(TokenType.END, "This module is missing its closing `end`.", "`end`")
        self._validate_module_contains_definitions_only(body)
        return ast.ModuleDefinition(
            module_token.location,
            [name_token.lexeme for name_token in name_tokens],
            body,
        )

    def _validate_module_contains_definitions_only(
        self,
        module_body: list[ast.Statement],
    ) -> None:
        """Reject actions in a namespace before any of its definitions load.

        A module answers “what exists?” and loading it must not perform an
        application action. These are definitions:

        * ``MAX_RETRIES = 5`` names a constant.
        * ``struct User ... end`` describes data.
        * ``fn find_user() ... end`` describes behavior for later use.

        In contrast, ``user = User()`` creates runtime state and ``print user``
        performs I/O. Rejecting the whole module during parsing prevents earlier
        definitions from being installed before the invalid action is found.
        """

        for statement in module_body:
            if self._is_allowed_module_definition(statement):
                continue

            raise ModuleContentError(
                statement.location,
                "Runtime statement found at module level.\n\n"
                "Modules can only contain:\n"
                "    import\n"
                "    constant\n"
                "    struct\n"
                "    function\n\n"
                "Move this code inside a function.",
            )

    @staticmethod
    def _is_allowed_module_definition(statement: ast.Statement) -> bool:
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

    def _parse_import(self, import_token: Token) -> ast.ImportStatement:
        name_tokens = self._parse_dotted_name("`import` must be followed by a module or member name.")
        alias = None
        selected_names: list[str] = []

        if self._match(TokenType.AS):
            alias_token = self._consume(
                TokenType.IDENTIFIER,
                "An import alias needs a name after `as`.",
                "an alias name",
            )
            alias = alias_token.lexeme

        elif self._match(TokenType.COLON):
            self._require_line_after_header("selected import")
            self._skip_newlines()

            # A trailing comma tells the parser another selected name follows.
            # This avoids assigning semantic meaning to indentation. For example:
            #
            #     import Text:
            #         trim,
            #         lowercase
            #
            # ``lowercase`` has no comma, so the following line begins a normal
            # statement even if both lines happen to use the same indentation.
            while True:
                selected_token = self._consume(
                    TokenType.IDENTIFIER,
                    "A selected import must name a module member.",
                    "a function, struct, or constant name",
                )
                selected_names.append(selected_token.lexeme)

                if not self._match(TokenType.COMMA):
                    break
                self._skip_newlines()

        return ast.ImportStatement(
            import_token.location,
            [name_token.lexeme for name_token in name_tokens],
            alias,
            selected_names,
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

    def _parse_when_statement(self, when_token: Token) -> ast.WhenStatement:
        matched_expression = self._parse_expression()
        binding_name = None
        if self._match(TokenType.AS):
            binding_token = self._consume(
                TokenType.IDENTIFIER,
                "`as` must be followed by a local binding name.",
                "a snake_case variable name",
            )
            validate_variable_name(binding_token.lexeme, binding_token.location)
            binding_name = binding_token.lexeme

        self._require_line_after_header("when expression")
        branches: list[ast.WhenBranch] = []
        self._skip_newlines()

        while not self._check(TokenType.END) and not self._is_at_end():
            pattern = self._parse_when_pattern()
            self._require_line_after_header("when pattern")
            branch_body = self._parse_block_until(self._starts_when_pattern_or_end)
            branches.append(ast.WhenBranch(pattern, branch_body))

        self._consume(TokenType.END, "This `when` expression is missing its closing `end`.", "`end`")
        return ast.WhenStatement(when_token.location, matched_expression, binding_name, branches)

    def _parse_when_pattern(self) -> ast.WhenPattern:
        if self._match(TokenType.NIL):
            return ast.NilPattern(self._previous().location)
        if self._match(TokenType.WILDCARD):
            return ast.WildcardPattern(self._previous().location)
        if self._check(TokenType.IDENTIFIER):
            pattern_token = self._advance()
            validate_struct_name(pattern_token.lexeme, pattern_token.location)
            return ast.StructPattern(pattern_token.lexeme, pattern_token.location)

        raise ParserError(
            self._peek().location,
            "A `when` branch must begin with a struct, `nil`, or the `_` wildcard.",
            expected="a pattern such as `User`, `nil`, or `_`",
            found=self._peek().describe(),
        )

    def _starts_when_pattern_or_end(self) -> bool:
        if self._check(TokenType.END):
            return True
        if self._check_any(TokenType.NIL, TokenType.WILDCARD):
            return self._peek_next().token_type is TokenType.NEWLINE
        if not self._check(TokenType.IDENTIFIER):
            return False

        is_pascal_case_name = PASCAL_CASE_PATTERN.fullmatch(self._peek().lexeme) is not None
        is_the_only_token_on_line = self._peek_next().token_type is TokenType.NEWLINE
        return is_pascal_case_name and is_the_only_token_on_line

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

    def _parse_assignment(self) -> ast.Expression:
        assignment_target = self._parse_equality()
        if not self._match(TokenType.ASSIGN):
            return assignment_target

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
                    "A dot must be followed by a field or module member name.",
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
                    and self._peek_next().token_type is TokenType.COLON
                )
                if begins_named_argument:
                    argument_name = self._advance().lexeme
                    self._advance()  # The lookahead above already proved this is `:`.

                argument_value = self._parse_expression()
                arguments.append(ast.CallArgument(argument_value, argument_name))
                self._skip_newlines()

                if not self._match(TokenType.COMMA):
                    break
                self._skip_newlines()

        self._consume(
            TokenType.RIGHT_PARENTHESIS,
            "This function or struct call is missing its closing parenthesis.",
            "`)`",
        )
        return ast.CallExpression(opening_parenthesis.location, callable_expression, arguments)

    def _parse_primary(self) -> ast.Expression:
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
