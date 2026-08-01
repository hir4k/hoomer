from __future__ import annotations

import unittest

from hoomer import ast
from hoomer.errors import NamingHoomerError, ParserError
from hoomer.lexer import Lexer
from hoomer.parser import Parser


def parse(source_code: str) -> ast.Program:
    return Parser(Lexer(source_code, "parser_test.hmr").scan_tokens()).parse()


class ParserTests(unittest.TestCase):
    def test_import_uses_an_unquoted_connected_package_path(self) -> None:
        program = Parser(
            Lexer("import kenekoi/accounts as ProjectAccounts\n").scan_tokens()
        ).parse()

        import_statement = program.statements[0]
        self.assertIsInstance(import_statement, ast.ImportStatement)
        self.assertEqual(import_statement.package_path, "kenekoi/accounts")
        self.assertEqual(import_statement.alias, "ProjectAccounts")

    def test_import_rejects_strings_and_whitespace_around_slashes(self) -> None:
        with self.assertRaises(ParserError) as quoted_error:
            Parser(Lexer('import "kenekoi/accounts"\n').scan_tokens()).parse()

        self.assertIn("package path", str(quoted_error.exception))

        with self.assertRaises(ParserError) as spaced_error:
            Parser(Lexer("import kenekoi / accounts\n").scan_tokens()).parse()

        self.assertIn("cannot contain whitespace", str(spaced_error.exception))

        with self.assertRaises(NamingHoomerError) as uppercase_error:
            Parser(Lexer("import Kenekoi/accounts\n").scan_tokens()).parse()

        self.assertIn("snake_case segments", str(uppercase_error.exception))

    def test_parser_honors_arithmetic_precedence(self) -> None:
        program = parse("result = 2 + 3 * 4\n")

        statement = program.statements[0]
        self.assertIsInstance(statement, ast.ExpressionStatement)
        assignment = statement.expression
        self.assertIsInstance(assignment, ast.AssignmentExpression)
        self.assertIsInstance(assignment.value, ast.BinaryExpression)
        self.assertEqual(assignment.value.operator, "+")
        self.assertIsInstance(assignment.value.right_operand, ast.BinaryExpression)
        self.assertEqual(assignment.value.right_operand.operator, "*")

    def test_parser_builds_an_inclusive_range_expression(self) -> None:
        program = parse("numbers = 0..10\n")

        assignment = program.statements[0].expression
        self.assertIsInstance(assignment, ast.AssignmentExpression)
        range_expression = assignment.value
        self.assertIsInstance(range_expression, ast.RangeExpression)
        self.assertEqual(range_expression.first_value.value, 0)
        self.assertEqual(range_expression.last_value.value, 10)

    def test_parser_builds_inline_when_with_required_fallback(self) -> None:
        program = parse(
            "connection = connect!() when DatabaseConnection else nil\n"
        )

        assignment = program.statements[0].expression
        self.assertIsInstance(assignment, ast.AssignmentExpression)
        inline_when = assignment.value
        self.assertIsInstance(inline_when, ast.InlineWhenExpression)
        self.assertIsInstance(inline_when.matched_expression, ast.CallExpression)
        self.assertIsInstance(inline_when.pattern, ast.StructPattern)
        self.assertEqual(inline_when.pattern.name_path, ["DatabaseConnection"])
        self.assertIsInstance(inline_when.fallback_expression, ast.LiteralExpression)
        self.assertIsNone(inline_when.fallback_expression.value)

        with self.assertRaises(ParserError) as caught_error:
            parse("connection = connect!() when DatabaseConnection\n")

        self.assertIn("requires an explicit `else` fallback", str(caught_error.exception))


    def test_parser_supports_multiline_named_struct_arguments(self) -> None:
        program = parse(
            """user = User(
    name: "Hirak",
    age: 26,
)
"""
        )

        assignment = program.statements[0].expression
        self.assertIsInstance(assignment, ast.AssignmentExpression)
        self.assertIsInstance(assignment.value, ast.CallExpression)
        self.assertEqual([argument.name for argument in assignment.value.arguments], ["name", "age"])


    def test_parser_rejects_names_that_hide_their_role(self) -> None:
        with self.assertRaises(NamingHoomerError) as caught_error:
            parse("fn BadFunctionName()\nend\n")

        self.assertIn("snake_case", str(caught_error.exception))
        self.assertIn("BadFunctionName", str(caught_error.exception))


    def test_parser_reports_the_expected_expression(self) -> None:
        with self.assertRaises(ParserError) as caught_error:
            parse("value = )\n")

        rendered_error = str(caught_error.exception)
        self.assertIn("parser_test.hmr", rendered_error)
        self.assertIn("Expected:\n    an expression", rendered_error)
        self.assertIn("Found:\n    )", rendered_error)
