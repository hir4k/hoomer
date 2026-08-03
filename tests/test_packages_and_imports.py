from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hoomer.errors import PackageContentError, RuntimeHoomerError
from hoomer.interpreter import Interpreter


class PackagesAndImportsTests(unittest.TestCase):
    def test_language_does_not_reserve_standard_package_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            external_io_directory = package_root / "std" / "io"
            external_io_directory.mkdir(parents=True)
            (external_io_directory / "io.hmr").write_text(
                """pub fn message()
    "ordinary dependency"
end
""",
                encoding="utf-8",
            )

            interpreter, output = Interpreter.capture_output(
                package_search_paths=[package_root]
            )
            interpreter.execute_source(
                "import std/io\nprint(io.message())\n"
            )

        loaded_io = interpreter.package_registry.get("std/io")
        self.assertIsNotNone(loaded_io)
        self.assertEqual(output.getvalue(), "ordinary dependency\n")
        self.assertEqual(loaded_io.source_directory, external_io_directory.resolve())

    def test_project_can_use_a_former_standard_package_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory) / "std"
            package_directory = project_root / "io"
            package_directory.mkdir(parents=True)
            (project_root / "hoomer.toml").write_text("", encoding="utf-8")
            (package_directory / "io.hmr").write_text(
                "fn main\nend\n",
                encoding="utf-8",
            )

            loaded_package = Interpreter().check_package(package_directory)

        self.assertEqual(loaded_package.import_path, "std/io")

    def test_directory_name_becomes_the_package_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            package_directory = package_root / "accounts"
            package_directory.mkdir()
            (package_directory / "accounts.hmr").write_text(
                """pub fn login()
    "logged in"
end

pub fn logout()
    "logged out"
end
""",
                encoding="utf-8",
            )

            interpreter, output = Interpreter.capture_output(
                package_search_paths=[package_root]
            )
            interpreter.execute_source(
                "import accounts\nprint(accounts.login())\n"
                "print(accounts.logout())\n"
            )

        self.assertEqual(output.getvalue(), "logged in\nlogged out\n")
        loaded_package = interpreter.package_registry.get("accounts")
        self.assertIsNotNone(loaded_package)
        self.assertEqual(loaded_package.name, "accounts")

    def test_files_in_one_directory_share_private_package_declarations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "accounts"
            package_directory.mkdir()
            (package_directory / "user.hmr").write_text(
                """fn normalized_name(name)
    name
end
""",
                encoding="utf-8",
            )
            (package_directory / "login.hmr").write_text(
                """
fn login(name)
    normalized_name(name)
end

fn main
    print(login("Hirak"))
end
""",
                encoding="utf-8",
            )

            interpreter, output = Interpreter.capture_output()
            interpreter.execute_package(package_directory)

        self.assertEqual(output.getvalue(), "Hirak\n")

    def test_imports_are_file_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            package_directory = package_root / "accounts"
            tools_directory = package_root / "tools"
            package_directory.mkdir()
            tools_directory.mkdir()
            (tools_directory / "tools.hmr").write_text(
                """pub fn normalize(name)
    name
end
""",
                encoding="utf-8",
            )
            (package_directory / "user.hmr").write_text(
                """import tools:
    normalize

fn normalized_name(name)
    normalize(name)
end
""",
                encoding="utf-8",
            )
            (package_directory / "main.hmr").write_text(
                """
fn main
    print(normalize("unavailable here"))
end
""",
                encoding="utf-8",
            )

            interpreter = Interpreter(package_search_paths=[package_root])
            with self.assertRaises(RuntimeHoomerError) as caught_error:
                interpreter.execute_package(package_directory)

        self.assertIn("`normalize` has not been defined", str(caught_error.exception))

    def test_whole_package_imports_are_file_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            accounts_directory = package_root / "accounts"
            application_directory = package_root / "application"
            accounts_directory.mkdir()
            application_directory.mkdir()
            (accounts_directory / "accounts.hmr").write_text(
                "pub fn name()\n    \"Accounts\"\nend\n",
                encoding="utf-8",
            )
            (application_directory / "helper.hmr").write_text(
                "import accounts\n\nfn helper()\n    accounts.name()\nend\n",
                encoding="utf-8",
            )
            (application_directory / "main.hmr").write_text(
                "fn main\n"
                "    print(accounts.name())\nend\n",
                encoding="utf-8",
            )

            interpreter = Interpreter(package_search_paths=[package_root])
            with self.assertRaises(RuntimeHoomerError) as caught_error:
                interpreter.execute_package(application_directory)

        self.assertIn("`accounts` has not been defined", str(caught_error.exception))

    def test_imports_package_with_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            accounts_directory = package_root / "accounts"
            application_directory = package_root / "application"
            accounts_directory.mkdir()
            application_directory.mkdir()
            (accounts_directory / "teacher.hmr").write_text(
                """pub struct Teacher
    name: "",
end
""",
                encoding="utf-8",
            )
            (application_directory / "main.hmr").write_text(
                """import accounts as TeacherAccount

fn main
    teacher = TeacherAccount.Teacher(name: "Hirak")
    print(teacher.name)
end
""",
                encoding="utf-8",
            )

            interpreter, output = Interpreter.capture_output(
                package_search_paths=[package_root]
            )
            interpreter.execute_package(application_directory)

        self.assertEqual(output.getvalue(), "Hirak\n")

    def test_installed_and_local_packages_can_share_a_directory_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workspace = Path(temporary_directory)
            project_root = workspace / "kenekoi"
            application_directory = project_root / "application"
            local_accounts_directory = project_root / "accounts"
            installed_accounts_directory = workspace / "accounts"
            application_directory.mkdir(parents=True)
            local_accounts_directory.mkdir()
            installed_accounts_directory.mkdir()
            (project_root / "hoomer.toml").write_text(
                "# Hoomer project root\n",
                encoding="utf-8",
            )
            (local_accounts_directory / "accounts.hmr").write_text(
                'pub fn source()\n    "project"\nend\n',
                encoding="utf-8",
            )
            (installed_accounts_directory / "accounts.hmr").write_text(
                'pub fn source()\n    "installed"\nend\n',
                encoding="utf-8",
            )
            (application_directory / "main.hmr").write_text(
                """import accounts as InstalledAccounts
import kenekoi/accounts as ProjectAccounts

fn main
    print(InstalledAccounts.source())
    print(ProjectAccounts.source())
end
""",
                encoding="utf-8",
            )

            interpreter, output = Interpreter.capture_output(
                package_search_paths=[workspace]
            )
            interpreter.execute_package(application_directory)

        self.assertEqual(output.getvalue(), "installed\nproject\n")
        self.assertIsNotNone(interpreter.package_registry.get("accounts"))
        self.assertIsNotNone(interpreter.package_registry.get("kenekoi/accounts"))

    def test_local_imports_start_with_the_project_root_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory) / "kenekoi"
            accounts_directory = project_root / "accounts"
            application_directory = project_root / "application"
            accounts_directory.mkdir(parents=True)
            application_directory.mkdir()
            (project_root / "hoomer.toml").write_text(
                "# Hoomer project root\n",
                encoding="utf-8",
            )
            (accounts_directory / "accounts.hmr").write_text(
                'pub fn greeting()\n    "hello"\nend\n',
                encoding="utf-8",
            )
            (application_directory / "main.hmr").write_text(
                """import kenekoi/accounts

fn main
    print(accounts.greeting())
end
""",
                encoding="utf-8",
            )

            interpreter, output = Interpreter.capture_output()
            interpreter.execute_package(application_directory)

        self.assertEqual(output.getvalue(), "hello\n")

    def test_unprefixed_import_does_not_fall_back_to_a_local_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_root = Path(temporary_directory) / "kenekoi"
            accounts_directory = project_root / "accounts"
            application_directory = project_root / "application"
            accounts_directory.mkdir(parents=True)
            application_directory.mkdir()
            (project_root / "hoomer.toml").write_text(
                "# Hoomer project root\n",
                encoding="utf-8",
            )
            (accounts_directory / "accounts.hmr").write_text(
                'pub fn greeting()\n    "hello"\nend\n',
                encoding="utf-8",
            )
            (application_directory / "main.hmr").write_text(
                "import accounts\n\nfn main\nend\n",
                encoding="utf-8",
            )

            interpreter = Interpreter(package_search_paths=[project_root])
            with self.assertRaises(RuntimeHoomerError) as caught_error:
                interpreter.execute_package(application_directory)

        rendered_error = str(caught_error.exception)
        self.assertIn("Could not find import `accounts`", rendered_error)
        self.assertIn("`kenekoi/accounts` for the local package", rendered_error)

    def test_package_reflection_lists_public_functions_and_structs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            package_directory = package_root / "accounts"
            package_directory.mkdir()
            (package_directory / "accounts.hmr").write_text(
                """pub struct User
    name,
end

pub fn find_user()
    nil
end
""",
                encoding="utf-8",
            )

            interpreter, output = Interpreter.capture_output(
                package_search_paths=[package_root]
            )
            interpreter.execute_source(
                """import accounts
package_info = reflection(accounts)
print(package_info.name)
print(package_info.path)
print(package_info.functions)
print(package_info.structs)
"""
            )

        self.assertEqual(
            output.getvalue(),
            'accounts\naccounts\n["find_user"]\n["User"]\n',
        )

    def test_package_accepts_inert_constants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            package_directory = package_root / "accounts"
            package_directory.mkdir()
            (package_directory / "accounts.hmr").write_text(
                """pub MAX_LOGIN_ATTEMPTS = 5
pub SUPPORTED_PORTS = [3000, 3001]
""",
                encoding="utf-8",
            )

            interpreter, output = Interpreter.capture_output(
                package_search_paths=[package_root]
            )
            interpreter.execute_source(
                "import accounts\n"
                "print(accounts.MAX_LOGIN_ATTEMPTS)\n"
                "print(accounts.SUPPORTED_PORTS)\n"
            )

        self.assertEqual(output.getvalue(), "5\n[3000, 3001]\n")

    def test_package_rejects_runtime_statements_and_active_constants(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "accounts"
            package_directory.mkdir()
            source_path = package_directory / "accounts.hmr"
            source_path.write_text('print("loading")\n', encoding="utf-8")

            with self.assertRaises(PackageContentError) as statement_error:
                Interpreter().check_package(package_directory)

            source_path.write_text("DATABASE = connect()\n", encoding="utf-8")
            with self.assertRaises(PackageContentError) as constant_error:
                Interpreter().check_package(package_directory)

        self.assertIn(
            "Runtime statement found at package level",
            str(statement_error.exception),
        )
        self.assertIn("constants cannot execute code", str(constant_error.exception))

    def test_every_file_in_a_directory_automatically_joins_the_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "accounts"
            package_directory.mkdir()
            (package_directory / "user.hmr").write_text(
                "pub struct User name end\n",
                encoding="utf-8",
            )
            (package_directory / "invoice.hmr").write_text(
                "pub struct Invoice total end\n",
                encoding="utf-8",
            )

            loaded_package = Interpreter().check_package(package_directory)

        self.assertEqual(loaded_package.name, "accounts")
        self.assertEqual(loaded_package.public_member_names, {"User", "Invoice"})

    def test_package_rejects_duplicate_declarations_across_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "accounts"
            package_directory.mkdir()
            (package_directory / "first.hmr").write_text(
                "fn find_user()\n    nil\nend\n",
                encoding="utf-8",
            )
            (package_directory / "second.hmr").write_text(
                "fn find_user()\n    nil\nend\n",
                encoding="utf-8",
            )

            with self.assertRaises(PackageContentError) as caught_error:
                Interpreter().check_package(package_directory)

        self.assertIn("`find_user` is duplicated", str(caught_error.exception))

    def test_main_must_be_callable_without_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "application"
            package_directory.mkdir()
            (package_directory / "main.hmr").write_text(
                "fn main(name)\n    print(name)\nend\n",
                encoding="utf-8",
            )

            with self.assertRaises(RuntimeHoomerError) as caught_error:
                Interpreter().execute_package(package_directory)

        self.assertIn(
            "entry point must be callable without arguments",
            str(caught_error.exception),
        )

    def test_package_import_cycles_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            first_directory = package_root / "first"
            second_directory = package_root / "second"
            first_directory.mkdir()
            second_directory.mkdir()
            (first_directory / "first.hmr").write_text(
                "import second\n\nfn first()\n    nil\nend\n",
                encoding="utf-8",
            )
            (second_directory / "second.hmr").write_text(
                "import first\n\nfn second()\n    nil\nend\n",
                encoding="utf-8",
            )

            interpreter = Interpreter(package_search_paths=[package_root])
            with self.assertRaises(RuntimeHoomerError) as caught_error:
                interpreter.check_package(first_directory)

        self.assertIn("circular import", str(caught_error.exception))
        self.assertIsNone(interpreter.package_registry.get("first"))
        self.assertIsNone(interpreter.package_registry.get("second"))

    def test_private_package_member_requires_pub_outside_its_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            package_directory = package_root / "accounts"
            package_directory.mkdir()
            (package_directory / "accounts.hmr").write_text(
                """fn internal_helper()
    "hidden"
end
""",
                encoding="utf-8",
            )

            interpreter = Interpreter(package_search_paths=[package_root])
            with self.assertRaises(RuntimeHoomerError) as caught_error:
                interpreter.execute_source(
                    "import accounts\naccounts.internal_helper()\n"
                )

        rendered_error = str(caught_error.exception)
        self.assertIn("private to package", rendered_error)
        self.assertIn("Add `pub`", rendered_error)
