"""Validation for the naming shapes that make Hoomer code self-describing."""

from __future__ import annotations

import re

from hoomer.errors import NamingHoomerError, SourceLocation


PASCAL_CASE_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9]*$")
SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
CONSTANT_CASE_PATTERN = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")


def validate_module_name(name: str, location: SourceLocation) -> None:
    _require_pattern(
        name,
        PASCAL_CASE_PATTERN,
        location,
        "Module names use PascalCase, for example `Authentication` or `LoginService`.",
    )


def validate_struct_name(name: str, location: SourceLocation) -> None:
    _require_pattern(
        name,
        PASCAL_CASE_PATTERN,
        location,
        "Struct names use PascalCase, for example `User` or `DatabaseError`.",
    )


def validate_function_name(name: str, location: SourceLocation) -> None:
    name_without_marker = name[:-1] if name.endswith(("?", "!")) else name
    _require_pattern(
        name_without_marker,
        SNAKE_CASE_PATTERN,
        location,
        "Function names use snake_case, optionally followed by `?` or `!`; "
        "for example `find_user`, `active?`, or `save_user!`.",
    )


def validate_variable_name(name: str, location: SourceLocation) -> None:
    is_variable = SNAKE_CASE_PATTERN.fullmatch(name) is not None
    is_constant = CONSTANT_CASE_PATTERN.fullmatch(name) is not None
    if is_variable or is_constant:
        return

    raise NamingHoomerError(
        location,
        "Variable names use snake_case and constants use UPPER_SNAKE_CASE.",
        expected="a name such as `current_user` or `MAX_CONNECTIONS`",
        found=name,
    )


def validate_field_name(name: str, location: SourceLocation) -> None:
    _require_pattern(
        name,
        SNAKE_CASE_PATTERN,
        location,
        "Struct fields use snake_case, for example `first_name` or `created_at`.",
    )


def _require_pattern(
    name: str,
    required_pattern: re.Pattern[str],
    location: SourceLocation,
    explanation: str,
) -> None:
    if required_pattern.fullmatch(name):
        return

    raise NamingHoomerError(
        location,
        explanation,
        expected="a name following the documented naming convention",
        found=name,
    )

