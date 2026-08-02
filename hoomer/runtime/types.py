"""Canonical runtime types used by Hoomer's cheap ``is`` operator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuntimeType:
    name: str


NIL = RuntimeType("Nil")
BOOLEAN = RuntimeType("Boolean")
INT = RuntimeType("Int")
FLOAT = RuntimeType("Float")
STRING = RuntimeType("String")
LIST = RuntimeType("List")
MAP = RuntimeType("Map")
RANGE = RuntimeType("Range")
FUNCTION = RuntimeType("Function")
BLOCK = RuntimeType("Block")
PACKAGE = RuntimeType("Package")
TYPE = RuntimeType("Type")
REFLECTION = RuntimeType("ReflectionInfo")

BUILTIN_TYPES = (
    NIL,
    BOOLEAN,
    INT,
    FLOAT,
    STRING,
    LIST,
    MAP,
    RANGE,
    FUNCTION,
    BLOCK,
    PACKAGE,
    TYPE,
    REFLECTION,
)


def type_of(value: object) -> object:
    """Return one canonical type object without allocating metadata."""

    from hoomer.runtime.functions import BuiltinFunction, RuntimeBlock, RuntimeFunction
    from hoomer.runtime.maps import RuntimeMap
    from hoomer.runtime.packages import RuntimePackage
    from hoomer.runtime.reflection import ReflectionValue
    from hoomer.runtime.structs import RuntimeStructDefinition, RuntimeStructInstance

    if value is None:
        return NIL
    if isinstance(value, bool):
        return BOOLEAN
    if isinstance(value, int):
        return INT
    if isinstance(value, float):
        return FLOAT
    if isinstance(value, str):
        return STRING
    if isinstance(value, RuntimeStructInstance):
        return value.definition
    if isinstance(value, RuntimeStructDefinition):
        return TYPE
    if isinstance(value, RuntimeType):
        return TYPE
    if isinstance(value, RuntimeBlock):
        return BLOCK
    if isinstance(value, (RuntimeFunction, BuiltinFunction)):
        return FUNCTION
    if isinstance(value, RuntimePackage):
        return PACKAGE
    if isinstance(value, list):
        return LIST
    if isinstance(value, RuntimeMap):
        return MAP
    if isinstance(value, range):
        return RANGE
    if isinstance(value, ReflectionValue):
        return REFLECTION
    return RuntimeType(type(value).__name__)


def is_type(value: object) -> bool:
    from hoomer.runtime.structs import RuntimeStructDefinition

    return isinstance(value, (RuntimeType, RuntimeStructDefinition))


def value_is_type(value: object, expected_type: object) -> bool:
    if not is_type(expected_type):
        return False
    return type_of(value) is expected_type
