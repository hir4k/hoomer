from __future__ import annotations

import unittest

from hoomer.errors import LexerError
from hoomer.lexer import Lexer
from hoomer.tokens import TokenType


class LexerTests(unittest.TestCase):
    def test_lexer_recognizes_literals_keywords_marked_names_and_operators(self) -> None:
        source = 'fn is_active(user)\n user.age >= 18 != false\n "Hello" nil _\nend\n'

        tokens = Lexer(source, "tokens.hmr").scan_tokens()
        token_types = [token.token_type for token in tokens]

        self.assertEqual(token_types, [
            TokenType.FUNCTION,
            TokenType.IDENTIFIER,
            TokenType.LEFT_PARENTHESIS,
            TokenType.IDENTIFIER,
            TokenType.RIGHT_PARENTHESIS,
            TokenType.NEWLINE,
            TokenType.IDENTIFIER,
            TokenType.DOT,
            TokenType.IDENTIFIER,
            TokenType.GREATER_EQUAL,
            TokenType.NUMBER,
            TokenType.NOT_EQUAL,
            TokenType.FALSE,
            TokenType.NEWLINE,
            TokenType.STRING,
            TokenType.NIL,
            TokenType.WILDCARD,
            TokenType.NEWLINE,
            TokenType.END,
            TokenType.NEWLINE,
            TokenType.END_OF_FILE,
        ])
        self.assertEqual(tokens[1].lexeme, "is_active")
        self.assertEqual(tokens[10].literal, 18)
        self.assertEqual(tokens[14].literal, "Hello")
        self.assertEqual(tokens[8].location.line, 2)
        self.assertEqual(tokens[8].location.column, 7)


    def test_lexer_decodes_supported_string_escapes(self) -> None:
        tokens = Lexer(r'"line one\n\"line two\""').scan_tokens()

        self.assertEqual(tokens[0].literal, 'line one\n"line two"')

    def test_lexer_recognizes_visibility_list_and_loop_tokens(self) -> None:
        tokens = Lexer(
            "package Accounts\npub for user in [users]\ncontinue\nignore save!()\n"
        ).scan_tokens()

        self.assertEqual(
            [token.token_type for token in tokens],
            [
                TokenType.PACKAGE,
                TokenType.IDENTIFIER,
                TokenType.NEWLINE,
                TokenType.PUBLIC,
                TokenType.FOR,
                TokenType.IDENTIFIER,
                TokenType.IN,
                TokenType.LEFT_BRACKET,
                TokenType.IDENTIFIER,
                TokenType.RIGHT_BRACKET,
                TokenType.NEWLINE,
                TokenType.CONTINUE,
                TokenType.NEWLINE,
                TokenType.IGNORE,
                TokenType.IDENTIFIER,
                TokenType.LEFT_PARENTHESIS,
                TokenType.RIGHT_PARENTHESIS,
                TokenType.NEWLINE,
                TokenType.END_OF_FILE,
            ],
        )

    def test_question_mark_is_not_part_of_a_function_name(self) -> None:
        with self.assertRaises(LexerError):
            Lexer("fn active?(user)\nend\n").scan_tokens()

    def test_lexer_distinguishes_ranges_from_field_access_and_decimals(self) -> None:
        tokens = Lexer("for number in 0..10\nuser.score 1.5\n").scan_tokens()

        self.assertEqual(
            [token.token_type for token in tokens],
            [
                TokenType.FOR,
                TokenType.IDENTIFIER,
                TokenType.IN,
                TokenType.NUMBER,
                TokenType.RANGE,
                TokenType.NUMBER,
                TokenType.NEWLINE,
                TokenType.IDENTIFIER,
                TokenType.DOT,
                TokenType.IDENTIFIER,
                TokenType.NUMBER,
                TokenType.NEWLINE,
                TokenType.END_OF_FILE,
            ],
        )

    def test_lexer_error_contains_file_line_column_and_context(self) -> None:
        with self.assertRaises(LexerError) as caught_error:
            Lexer("name = @", "broken.hmr").scan_tokens()

        rendered_error = str(caught_error.exception)
        self.assertIn("broken.hmr", rendered_error)
        self.assertIn("line 1, column 8", rendered_error)
        self.assertIn("Expected:", rendered_error)
        self.assertIn("Found:", rendered_error)
