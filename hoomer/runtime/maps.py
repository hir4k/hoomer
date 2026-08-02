"""Insertion-ordered maps with Hoomer-facing key semantics."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from hoomer.errors import RuntimeHoomerError, SourceLocation


MapKeyIdentity = tuple[str, object]


@dataclass(slots=True)
class MapEntryValue:
    key: object
    value: object


class RuntimeMap:
    """A mutable map whose keys are stable scalar Hoomer values.

    Structs and collections are mutable, so using them as keys would make an
    existing entry unreachable after mutation. Restricting keys to scalar
    values keeps lookup behavior predictable without exposing Python's hashing
    rules to Hoomer programs.
    """

    def __init__(self) -> None:
        self._entries: OrderedDict[MapKeyIdentity, MapEntryValue] = OrderedDict()

    def set(self, key: object, value: object, location: SourceLocation) -> object:
        key_identity = self._key_identity(key, location)
        existing_entry = self._entries.get(key_identity)
        if existing_entry is None:
            self._entries[key_identity] = MapEntryValue(key, value)
        else:
            existing_entry.value = value
        return value

    def get(self, key: object, location: SourceLocation) -> object:
        key_identity = self._key_identity(key, location)
        entry = self._entries.get(key_identity)
        return None if entry is None else entry.value

    def contains(self, key: object, location: SourceLocation) -> bool:
        key_identity = self._key_identity(key, location)
        return key_identity in self._entries

    def keys(self) -> list[object]:
        return [entry.key for entry in self._entries.values()]

    def items(self) -> list[tuple[object, object]]:
        return [(entry.key, entry.value) for entry in self._entries.values()]

    def __len__(self) -> int:
        return len(self._entries)

    def __eq__(self, other: object) -> bool:
        if self is other:
            return True
        if not isinstance(other, RuntimeMap) or len(self) != len(other):
            return False

        from hoomer.runtime.values import runtime_values_equal

        for key_identity, entry in self._entries.items():
            other_entry = other._entries.get(key_identity)
            if other_entry is None:
                return False
            if not runtime_values_equal(entry.value, other_entry.value):
                return False
        return True

    @staticmethod
    def _key_identity(key: object, location: SourceLocation) -> MapKeyIdentity:
        if key is None:
            return ("nil", None)
        if isinstance(key, bool):
            return ("boolean", key)
        if isinstance(key, (int, float)):
            return ("number", key)
        if isinstance(key, str):
            return ("string", key)

        from hoomer.runtime.values import runtime_type_name

        raise RuntimeHoomerError(
            location,
            f"A value of type {runtime_type_name(key)} cannot be used as a map key.",
            expected="a stable scalar key: string, number, boolean, or nil",
            found=runtime_type_name(key),
        )
