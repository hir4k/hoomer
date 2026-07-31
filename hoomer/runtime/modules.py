"""Module namespaces and the registry that connects qualified names."""

from __future__ import annotations

from hoomer.errors import RuntimeHoomerError, SourceLocation
from hoomer.runtime.environment import Environment


class RuntimeModule:
    def __init__(
        self,
        full_name: str,
        environment: Environment,
        *,
        is_builtin: bool = False,
    ) -> None:
        self.full_name = full_name
        self.environment = environment
        self.member_names: set[str] = set()
        self.is_builtin = is_builtin

    @property
    def short_name(self) -> str:
        return self.full_name.rsplit(".", 1)[-1]

    def register_member(self, member_name: str) -> None:
        """Make a declaration addressable through this module namespace.

        Hoomer modules have no visibility modifier. For example, defining
        ``fn login()`` inside ``Accounts`` automatically makes the function
        available as ``Accounts.login()``.
        """

        self.member_names.add(member_name)

    def get_member(
        self,
        member_name: str,
        location: SourceLocation,
    ) -> object:
        member_exists = self.environment.has_local(member_name)
        member_belongs_to_module = member_name in self.member_names
        if member_exists and member_belongs_to_module:
            return self.environment.get(member_name, location)

        explanation = f"Module `{self.full_name}` has no member named `{member_name}`."
        available_members = sorted(self.member_names)
        expected = "a module member"
        if available_members:
            expected += ": " + ", ".join(available_members)

        raise RuntimeHoomerError(
            location,
            explanation,
            expected=expected,
            found=member_name,
        )


class ModuleRegistry:
    """Own modules by full dotted name and preserve their parent relationships."""

    def __init__(self, global_environment: Environment) -> None:
        self.global_environment = global_environment
        self.modules_by_full_name: dict[str, RuntimeModule] = {}

    def get(self, name_path: list[str]) -> RuntimeModule | None:
        return self.modules_by_full_name.get(".".join(name_path))

    def get_or_create_path(self, name_path: list[str]) -> RuntimeModule:
        """Create missing namespaces from left to right.

        For ``module Authentication.LoginService``, the method creates (or
        reuses) ``Authentication`` first, then gives ``LoginService`` an
        environment whose parent is Authentication's environment. This mirrors
        lexical lookup and makes the dotted module tree require no second,
        parallel scoping mechanism.
        """

        parent_module: RuntimeModule | None = None
        accumulated_names: list[str] = []

        for path_part in name_path:
            accumulated_names.append(path_part)
            full_name = ".".join(accumulated_names)
            module = self.modules_by_full_name.get(full_name)

            if module is None:
                parent_environment = (
                    self.global_environment
                    if parent_module is None
                    else parent_module.environment
                )
                module = RuntimeModule(full_name, Environment(parent_environment))
                self.modules_by_full_name[full_name] = module

                if parent_module is None:
                    if not self.global_environment.has_local(path_part):
                        self.global_environment.define(path_part, module)
                else:
                    if not parent_module.environment.has_local(path_part):
                        parent_module.environment.define(path_part, module)
                    parent_module.register_member(path_part)

            parent_module = module

        if parent_module is None:
            raise ValueError("A module path must contain at least one name.")
        return parent_module

    def register_builtin(self, module: RuntimeModule) -> None:
        self.modules_by_full_name[module.full_name] = module
        self.global_environment.define(module.short_name, module)
