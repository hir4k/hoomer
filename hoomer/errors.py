"""Source-aware errors shared by every stage of the interpreter."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """A human-readable position in a source file.

    Lines and columns are one-based because these positions are shown directly
    to people. Keeping that convention here avoids repeated ``+ 1`` adjustments
    throughout the lexer, parser, and runtime diagnostics.
    """

    file_name: str
    line: int
    column: int


class HoomerError(Exception):
    """Base class for failures that should be presented to a Hoomer programmer."""

    error_kind = "Hoomer error"

    def __init__(
        self,
        location: SourceLocation,
        explanation: str,
        *,
        expected: str | None = None,
        found: str | None = None,
    ) -> None:
        super().__init__(explanation)
        self.location = location
        self.explanation = explanation
        self.expected = expected
        self.found = found

    def __str__(self) -> str:
        location_heading = (
            f"{self.error_kind} in {self.location.file_name} "
            f"at line {self.location.line}, column {self.location.column}."
        )
        message_parts = [location_heading, "", self.explanation]

        if self.expected is not None:
            message_parts.extend(["", "Expected:", f"    {self.expected}"])

        if self.found is not None:
            message_parts.extend(["", "Found:", f"    {self.found}"])

        return "\n".join(message_parts)


class LexerError(HoomerError):
    error_kind = "Lexer error"


class ParserError(HoomerError):
    error_kind = "Syntax error"


class RuntimeHoomerError(HoomerError):
    error_kind = "Runtime error"


class NamingHoomerError(HoomerError):
    error_kind = "Naming error"


class PackageContentError(HoomerError):
    """Raised when a package file violates declarative package rules."""

    error_kind = "Hoomer Error"
