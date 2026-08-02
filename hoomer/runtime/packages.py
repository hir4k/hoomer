"""Runtime package values indexed by their stable import paths."""

from __future__ import annotations

from pathlib import Path

from hoomer.errors import RuntimeHoomerError, SourceLocation
from hoomer.runtime.environment import Environment


class RuntimePackage:
    def __init__(
        self,
        name: str,
        import_path: str,
        environment: Environment,
        *,
        source_directory: Path | None = None,
    ) -> None:
        self.name = name
        self.import_path = import_path
        self.environment = environment
        self.source_directory = source_directory
        self.member_names: set[str] = set()
        self.public_member_names: set[str] = set()

    def register_member(self, member_name: str) -> None:
        """Make a declaration addressable throughout this package."""

        self.member_names.add(member_name)

    def make_public(self, member_name: str) -> None:
        self.register_member(member_name)
        self.public_member_names.add(member_name)

    def get_member(
        self,
        member_name: str,
        location: SourceLocation,
    ) -> object:
        member_exists = self.environment.has_local(member_name)
        member_is_public = member_name in self.public_member_names
        if member_exists and member_is_public:
            return self.environment.get(member_name, location)

        if member_exists and member_name in self.member_names:
            explanation = (
                f"`{self.name}.{member_name}` is private to package "
                f"`{self.import_path}`. Add `pub` to expose it."
            )
        else:
            explanation = (
                f"Package `{self.import_path}` has no member named `{member_name}`."
            )

        available_members = sorted(self.public_member_names)
        expected = "a public package member"
        if available_members:
            expected += ": " + ", ".join(available_members)

        raise RuntimeHoomerError(
            location,
            explanation,
            expected=expected,
            found=member_name,
        )


class PackageRegistry:
    """Own packages by slash-separated import path for one Hoomer process."""

    def __init__(self, global_environment: Environment) -> None:
        self.global_environment = global_environment
        self.packages_by_import_path: dict[str, RuntimePackage] = {}

    def get(self, import_path: str) -> RuntimePackage | None:
        return self.packages_by_import_path.get(import_path)

    def get_or_create(
        self,
        name: str,
        import_path: str,
        *,
        source_directory: Path | None = None,
    ) -> RuntimePackage:
        package = self.get(import_path)
        if package is None:
            package = RuntimePackage(
                name,
                import_path,
                Environment(self.global_environment),
                source_directory=source_directory,
            )
            self.packages_by_import_path[import_path] = package
        elif source_directory is not None:
            package.source_directory = source_directory
        return package

    def discard(self, import_path: str) -> None:
        """Forget a package whose declarations failed to finish loading."""

        self.packages_by_import_path.pop(import_path, None)
