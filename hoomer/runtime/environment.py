"""Lexical environments that map Hoomer names to runtime values."""

from __future__ import annotations

from dataclasses import dataclass

from hoomer.errors import RuntimeHoomerError, SourceLocation


@dataclass(slots=True)
class Binding:
    value: object
    is_mutable: bool


class Environment:
    """One lexical scope, optionally linked to an enclosing scope.

    Looking up and assigning are deliberately separate operations. A lookup may
    walk outward freely, but an assignment must preserve the mutability of the
    binding it finds. This is how ``MAX_RETRIES = 3`` remains a constant even
    when referenced from a nested function.
    """

    def __init__(self, parent: Environment | None = None) -> None:
        self.parent = parent
        self._bindings: dict[str, Binding] = {}

    def define(
        self,
        name: str,
        value: object,
        *,
        is_mutable: bool = True,
        replace: bool = False,
        location: SourceLocation | None = None,
    ) -> None:
        name_already_exists = name in self._bindings
        if name_already_exists and not replace:
            error_location = location or SourceLocation("<runtime>", 1, 1)
            raise RuntimeHoomerError(
                error_location,
                f"The name `{name}` is already defined in this scope.",
                expected="a new name, or another function overload with a different arity",
                found=name,
            )

        self._bindings[name] = Binding(value, is_mutable)

    def get(self, name: str, location: SourceLocation) -> object:
        environment_with_name = self.find_environment_containing(name)
        if environment_with_name is None:
            raise RuntimeHoomerError(
                location,
                f"The name `{name}` has not been defined.",
                expected="a variable, function, struct, module, or imported name in scope",
                found=name,
            )
        return environment_with_name._bindings[name].value

    def assign(self, name: str, value: object, location: SourceLocation) -> object:
        environment_with_name = self.find_environment_containing(name)
        if environment_with_name is None:
            # Assignment is also Hoomer's declaration syntax. Only an absent name
            # creates a binding; an existing name in any enclosing lexical scope
            # is updated instead. Example: a function can update a captured local,
            # while ``new_name = value`` creates a function-local variable.
            self.define(
                name,
                value,
                is_mutable=not _is_constant_name(name),
                location=location,
            )
            return value

        existing_binding = environment_with_name._bindings[name]
        if not existing_binding.is_mutable:
            raise RuntimeHoomerError(
                location,
                f"`{name}` is a constant and cannot be assigned more than once.",
                expected="a new variable name or a mutable snake_case binding",
                found=name,
            )

        existing_binding.value = value
        return value

    def find_environment_containing(self, name: str) -> Environment | None:
        current_environment: Environment | None = self
        while current_environment is not None:
            if name in current_environment._bindings:
                return current_environment
            current_environment = current_environment.parent
        return None

    def get_local(self, name: str) -> object | None:
        binding = self._bindings.get(name)
        return None if binding is None else binding.value

    def has_local(self, name: str) -> bool:
        return name in self._bindings

    def local_items(self) -> list[tuple[str, object]]:
        return [(name, binding.value) for name, binding in self._bindings.items()]


def _is_constant_name(name: str) -> bool:
    return name.isupper() and any(character.isalpha() for character in name)

