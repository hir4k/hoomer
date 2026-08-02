"""Convert Hoomer source text into a source-positioned token stream."""

from __future__ import annotations

from hoomer.errors import LexerError, SourceLocation
from hoomer.tokens import KEYWORD_TOKEN_TYPES, Token, TokenType


class Lexer:
    """A deliberately direct, single-pass lexer.

    The implementation keeps the cursor, line, and column together. This is a
    little more bookkeeping than calculating locations after tokenization, but
    it means even an unfinished string can point at its exact opening quote.
    Excellent diagnostics are more valuable to this interpreter than shaving a
    few instructions from lexing.
    """

    def __init__(self, source_code: str, file_name: str = "<source>") -> None:
        self.source_code = source_code
        self.file_name = file_name
        self.tokens: list[Token] = []
        self.current_index = 0
        self.current_line = 1
        self.current_column = 1

    def scan_tokens(self) -> list[Token]:
        while not self._is_at_end():
            token_start_index = self.current_index
            token_start_line = self.current_line
            token_start_column = self.current_column
            current_character = self._advance()

            self._scan_token_starting_with(
                current_character,
                token_start_index,
                token_start_line,
                token_start_column,
            )

        end_location = SourceLocation(
            self.file_name,
            self.current_line,
            self.current_column,
        )
        self.tokens.append(Token(TokenType.END_OF_FILE, "", None, end_location))
        return self.tokens

    def _scan_token_starting_with(
        self,
        current_character: str,
        token_start_index: int,
        token_start_line: int,
        token_start_column: int,
    ) -> None:
        single_character_tokens = {
            "(": TokenType.LEFT_PARENTHESIS,
            ")": TokenType.RIGHT_PARENTHESIS,
            "{": TokenType.LEFT_BRACE,
            "}": TokenType.RIGHT_BRACE,
            "[": TokenType.LEFT_BRACKET,
            "]": TokenType.RIGHT_BRACKET,
            ",": TokenType.COMMA,
            ":": TokenType.COLON,
            "&": TokenType.AMPERSAND,
            "+": TokenType.PLUS,
            "-": TokenType.MINUS,
            "*": TokenType.STAR,
            "/": TokenType.SLASH,
            "%": TokenType.PERCENT,
        }

        if current_character in single_character_tokens:
            self._add_token(
                single_character_tokens[current_character],
                token_start_index,
                token_start_line,
                token_start_column,
            )
            return

        if current_character == ".":
            token_type = TokenType.RANGE if self._match(".") else TokenType.DOT
            self._add_token(
                token_type,
                token_start_index,
                token_start_line,
                token_start_column,
            )
            return

        if current_character == "=":
            token_type = TokenType.EQUAL if self._match("=") else TokenType.ASSIGN
            self._add_token(token_type, token_start_index, token_start_line, token_start_column)
            return

        if current_character == "!":
            if self._match("="):
                self._add_token(
                    TokenType.NOT_EQUAL,
                    token_start_index,
                    token_start_line,
                    token_start_column,
                )
                return
            self._raise_unexpected_character(current_character, token_start_line, token_start_column)

        if current_character == ">":
            token_type = TokenType.GREATER_EQUAL if self._match("=") else TokenType.GREATER
            self._add_token(token_type, token_start_index, token_start_line, token_start_column)
            return

        if current_character == "<":
            token_type = TokenType.LESS_EQUAL if self._match("=") else TokenType.LESS
            self._add_token(token_type, token_start_index, token_start_line, token_start_column)
            return

        if current_character == "\n":
            self._add_token(
                TokenType.NEWLINE,
                token_start_index,
                token_start_line,
                token_start_column,
            )
            return

        if current_character in {" ", "\r", "\t"}:
            return

        if current_character == "#":
            self._skip_comment()
            return

        if current_character == '"':
            self._scan_string(token_start_index, token_start_line, token_start_column)
            return

        if current_character.isdigit():
            self._scan_number(token_start_index, token_start_line, token_start_column)
            return

        if current_character.isalpha() or current_character == "_":
            self._scan_identifier(token_start_index, token_start_line, token_start_column)
            return

        self._raise_unexpected_character(current_character, token_start_line, token_start_column)

    def _scan_string(
        self,
        token_start_index: int,
        token_start_line: int,
        token_start_column: int,
    ) -> None:
        decoded_characters: list[str] = []
        escape_values = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}

        while not self._is_at_end() and self._peek() != '"':
            character = self._advance()
            if character == "\n":
                location = SourceLocation(self.file_name, token_start_line, token_start_column)
                raise LexerError(
                    location,
                    "Strings cannot continue onto the next line.",
                    expected='a closing double quote (\")',
                    found="end of line",
                )

            if character != "\\":
                decoded_characters.append(character)
                continue

            if self._is_at_end():
                break

            escaped_character = self._advance()
            decoded_value = escape_values.get(escaped_character)
            if decoded_value is None:
                escape_location = SourceLocation(
                    self.file_name,
                    self.current_line,
                    self.current_column - 1,
                )
                raise LexerError(
                    escape_location,
                    f"The escape sequence \\{escaped_character} is not supported.",
                    expected=r"one of: \n, \r, \t, \", or \\",
                    found=f"\\{escaped_character}",
                )
            decoded_characters.append(decoded_value)

        if self._is_at_end():
            location = SourceLocation(self.file_name, token_start_line, token_start_column)
            raise LexerError(
                location,
                "This string starts here but never closes.",
                expected='a closing double quote (\")',
                found="end of file",
            )

        self._advance()
        self._add_token(
            TokenType.STRING,
            token_start_index,
            token_start_line,
            token_start_column,
            "".join(decoded_characters),
        )

    def _scan_number(
        self,
        token_start_index: int,
        token_start_line: int,
        token_start_column: int,
    ) -> None:
        while self._peek().isdigit():
            self._advance()

        has_decimal_point = self._peek() == "." and self._peek_next().isdigit()
        if has_decimal_point:
            self._advance()
            while self._peek().isdigit():
                self._advance()

        number_text = self.source_code[token_start_index : self.current_index]
        number_value: int | float
        if has_decimal_point:
            number_value = float(number_text)
        else:
            number_value = int(number_text)

        self._add_token(
            TokenType.NUMBER,
            token_start_index,
            token_start_line,
            token_start_column,
            number_value,
        )

    def _scan_identifier(
        self,
        token_start_index: int,
        token_start_line: int,
        token_start_column: int,
    ) -> None:
        while self._peek().isalnum() or self._peek() == "_":
            self._advance()

        # ``!`` marks a function whose result deserves inspection. It remains
        # part of the name, while ``?`` is deliberately not another spelling
        # convention programmers have to learn.
        if self._peek() == "!":
            self._advance()

        identifier_text = self.source_code[token_start_index : self.current_index]
        if identifier_text == "_":
            token_type = TokenType.WILDCARD
        else:
            token_type = KEYWORD_TOKEN_TYPES.get(identifier_text, TokenType.IDENTIFIER)

        self._add_token(
            token_type,
            token_start_index,
            token_start_line,
            token_start_column,
        )

    def _skip_comment(self) -> None:
        while not self._is_at_end() and self._peek() != "\n":
            self._advance()

    def _add_token(
        self,
        token_type: TokenType,
        token_start_index: int,
        token_start_line: int,
        token_start_column: int,
        literal: object | None = None,
    ) -> None:
        lexeme = self.source_code[token_start_index : self.current_index]
        location = SourceLocation(self.file_name, token_start_line, token_start_column)
        self.tokens.append(Token(token_type, lexeme, literal, location))

    def _advance(self) -> str:
        character = self.source_code[self.current_index]
        self.current_index += 1

        if character == "\n":
            self.current_line += 1
            self.current_column = 1
        else:
            self.current_column += 1

        return character

    def _match(self, expected_character: str) -> bool:
        if self._is_at_end() or self.source_code[self.current_index] != expected_character:
            return False
        self._advance()
        return True

    def _peek(self) -> str:
        if self._is_at_end():
            return "\0"
        return self.source_code[self.current_index]

    def _peek_next(self) -> str:
        next_index = self.current_index + 1
        if next_index >= len(self.source_code):
            return "\0"
        return self.source_code[next_index]

    def _is_at_end(self) -> bool:
        return self.current_index >= len(self.source_code)

    def _raise_unexpected_character(self, character: str, line: int, column: int) -> None:
        location = SourceLocation(self.file_name, line, column)
        raise LexerError(
            location,
            f"The character {character!r} does not begin any Hoomer token.",
            expected="a literal, name, keyword, or supported operator",
            found=character,
        )
