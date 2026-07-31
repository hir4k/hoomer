"""Token definitions for Hoomer's intentionally small lexical vocabulary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from hoomer.errors import SourceLocation


class TokenType(Enum):
    # Single-character punctuation and operators.
    LEFT_PARENTHESIS = auto()
    RIGHT_PARENTHESIS = auto()
    LEFT_BRACE = auto()
    RIGHT_BRACE = auto()
    LEFT_BRACKET = auto()
    RIGHT_BRACKET = auto()
    COMMA = auto()
    DOT = auto()
    COLON = auto()
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    WILDCARD = auto()

    # Operators that may contain a second character.
    ASSIGN = auto()
    EQUAL = auto()
    NOT_EQUAL = auto()
    GREATER = auto()
    GREATER_EQUAL = auto()
    LESS = auto()
    LESS_EQUAL = auto()

    IDENTIFIER = auto()
    STRING = auto()
    NUMBER = auto()

    MODULE = auto()
    IMPORT = auto()
    STRUCT = auto()
    FUNCTION = auto()
    END = auto()
    IF = auto()
    ELSIF = auto()
    ELSE = auto()
    WHEN = auto()
    AS = auto()
    DO = auto()
    RETURN = auto()
    PUBLIC = auto()
    FOR = auto()
    IN = auto()
    CONTINUE = auto()
    TRUE = auto()
    FALSE = auto()
    NIL = auto()

    NEWLINE = auto()
    END_OF_FILE = auto()


KEYWORD_TOKEN_TYPES: dict[str, TokenType] = {
    "module": TokenType.MODULE,
    "import": TokenType.IMPORT,
    "struct": TokenType.STRUCT,
    "fn": TokenType.FUNCTION,
    "end": TokenType.END,
    "if": TokenType.IF,
    "elsif": TokenType.ELSIF,
    "else": TokenType.ELSE,
    "when": TokenType.WHEN,
    "as": TokenType.AS,
    "do": TokenType.DO,
    "return": TokenType.RETURN,
    "pub": TokenType.PUBLIC,
    "for": TokenType.FOR,
    "in": TokenType.IN,
    "continue": TokenType.CONTINUE,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "nil": TokenType.NIL,
}


@dataclass(frozen=True, slots=True)
class Token:
    token_type: TokenType
    lexeme: str
    literal: Any
    location: SourceLocation

    def describe(self) -> str:
        """Return the source spelling users expect to see in an error."""

        if self.token_type is TokenType.END_OF_FILE:
            return "end of file"
        if self.token_type is TokenType.NEWLINE:
            return "end of line"
        return self.lexeme
