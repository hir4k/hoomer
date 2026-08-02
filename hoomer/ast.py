"""Plain data nodes describing a parsed Hoomer program.

The AST intentionally contains no evaluation behavior. Keeping syntax as data
lets tools such as formatters and language servers reuse the parser without
also importing runtime state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from hoomer.errors import SourceLocation


@dataclass(slots=True)
class Program:
    statements: list[Statement]
    package_name: str | None = None
    package_location: SourceLocation | None = None


@dataclass(slots=True)
class Expression:
    location: SourceLocation


@dataclass(slots=True)
class LiteralExpression(Expression):
    value: object


@dataclass(slots=True)
class VariableExpression(Expression):
    name: str


@dataclass(slots=True)
class UnaryExpression(Expression):
    operator: str
    operand: Expression


@dataclass(slots=True)
class BinaryExpression(Expression):
    left_operand: Expression
    operator: str
    right_operand: Expression


@dataclass(slots=True)
class AssignmentExpression(Expression):
    target: VariableExpression | FieldAccessExpression | IndexAccessExpression
    value: Expression


@dataclass(slots=True)
class CallArgument:
    value: Expression
    name: str | None = None


@dataclass(slots=True)
class CallExpression(Expression):
    callable_expression: Expression
    arguments: list[CallArgument]
    block: Expression | None = None


@dataclass(slots=True)
class FieldAccessExpression(Expression):
    target: Expression
    field_name: str


@dataclass(slots=True)
class IndexAccessExpression(Expression):
    target: Expression
    index: Expression


@dataclass(slots=True)
class BlockExpression(Expression):
    """A ``do ... end`` body represented as a callable runtime value."""

    parameter_names: list[str]
    statements: list[Statement]


@dataclass(slots=True)
class TryExpression(Expression):
    expression: Expression


@dataclass(slots=True)
class ListExpression(Expression):
    items: list[Expression]


@dataclass(slots=True)
class MapEntry:
    key: Expression
    value: Expression


@dataclass(slots=True)
class MapExpression(Expression):
    entries: list[MapEntry]


@dataclass(slots=True)
class RangeExpression(Expression):
    first_value: Expression
    last_value: Expression


@dataclass(slots=True)
class Statement:
    location: SourceLocation


@dataclass(slots=True)
class ExpressionStatement(Statement):
    expression: Expression


@dataclass(slots=True)
class PrintStatement(Statement):
    expression: Expression


@dataclass(slots=True)
class ReturnStatement(Statement):
    expression: Expression | None


@dataclass(slots=True)
class FunctionParameterDefinition:
    """One function parameter and the way callers must supply it.

    ``is_named`` distinguishes ``host:`` from positional ``host``. Positional
    parameters are always required. A named parameter may be required
    (``host:``) or provide its default directly after the colon
    (``retries: 3``).
    """

    name: str
    location: SourceLocation
    is_named: bool
    default_value: Expression | None
    is_block: bool = False


@dataclass(slots=True)
class FunctionDefinition(Statement):
    name: str
    parameters: list[FunctionParameterDefinition]
    body: list[Statement]
    is_public: bool = False


@dataclass(slots=True)
class StructFieldDefinition:
    name: str
    location: SourceLocation
    default_value: Expression | None


@dataclass(slots=True)
class StructDefinition(Statement):
    name: str
    fields: list[StructFieldDefinition]
    is_public: bool = False
    is_error: bool = False


@dataclass(slots=True)
class PublicConstantDefinition(Statement):
    name: str
    value: Expression


@dataclass(slots=True)
class ImportStatement(Statement):
    package_path: str
    alias: str | None = None
    selected_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConditionalBranch:
    condition: Expression
    body: list[Statement]


@dataclass(slots=True)
class IfStatement(Statement):
    branches: list[ConditionalBranch]
    else_body: list[Statement] | None


@dataclass(slots=True)
class IfExpression(Expression):
    branches: list[ConditionalBranch]
    else_body: list[Statement] | None


@dataclass(slots=True)
class ForStatement(Statement):
    item_names: list[str]
    iterable_expression: Expression
    body: list[Statement]


@dataclass(slots=True)
class WhileStatement(Statement):
    condition: Expression
    body: list[Statement]


@dataclass(slots=True)
class BreakStatement(Statement):
    pass


@dataclass(slots=True)
class ContinueStatement(Statement):
    pass


@dataclass(slots=True)
class StructPattern:
    name_path: list[str]
    location: SourceLocation


@dataclass(slots=True)
class LiteralPattern:
    value: object
    location: SourceLocation


@dataclass(slots=True)
class NilPattern:
    location: SourceLocation


@dataclass(slots=True)
class ElsePattern:
    location: SourceLocation


WhenPattern: TypeAlias = StructPattern | LiteralPattern | NilPattern | ElsePattern


@dataclass(slots=True)
class WhenBranch:
    pattern: WhenPattern
    binding_name: str | None
    body: list[Statement]


@dataclass(slots=True)
class WhenExpression(Expression):
    matched_expression: Expression
    branches: list[WhenBranch]


@dataclass(slots=True)
class InlineWhenExpression(Expression):
    """Keep a matching value or evaluate an explicit fallback expression."""

    matched_expression: Expression
    pattern: WhenPattern
    fallback_expression: Expression
