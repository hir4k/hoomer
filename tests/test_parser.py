from __future__ import annotations

import unittest

from hoomer import ast
from hoomer.errors import NamingHoomerError, ParserError
from hoomer.lexer import Lexer
from hoomer.parser import Parser


def parse(source_code: str) -> ast.Program:
    return Parser(Lexer(source_code, "parser_test.hmr").scan_tokens()).parse()


class ParserTests(unittest.TestCase):
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


    def test_parser_supports_multiline_named_struct_arguments(self) -> None:
        program = parse(
            """user = User(
    name="Hirak",
    age=26,
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
