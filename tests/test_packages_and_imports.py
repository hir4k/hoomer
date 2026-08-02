from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hoomer.errors import PackageContentError, RuntimeHoomerError
from hoomer.interpreter import Interpreter
from tests.helpers import run_hoomer


class PackagesAndImportsTests(unittest.TestCase):
    def test_language_does_not_reserve_standard_package_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            external_io_directory = package_root / "std" / "io"
            external_io_directory.mkdir(parents=True)
            (external_io_directory / "io.hmr").write_text(
                """package IO

pub fn message()
    "ordinary dependency"
end
""",
                encoding="utf-8",
            )

            interpreter, output = Interpreter.capture_output(
                package_search_paths=[package_root]
            )
            interpreter.execute_source(
                "import std/io\nprint(IO.message())\n"
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
                "package IO\n\nfn main\nend\n",
                encoding="utf-8",
            )

            loaded_package = Interpreter().check_package(package_directory)

        self.assertEqual(loaded_package.import_path, "std/io")

    def test_package_header_owns_the_file_until_end_of_file(self) -> None:
        interpreter, output = Interpreter.capture_output()
        interpreter.execute_source(
            """package Accounts

pub fn login()
    "logged in"
end

pub fn logout()
    "logged out"
end
""",
            "accounts.hmr",
        )

        interpreter.execute_source(
            "import accounts\nprint(Accounts.login())\n"
            "print(Accounts.logout())\n"
        )

        self.assertEqual(output.getvalue(), "logged in\nlogged out\n")

    def test_files_in_one_directory_share_private_package_declarations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "accounts"
            package_directory.mkdir()
            (package_directory / "user.hmr").write_text(
                """package Accounts

fn normalized_name(name)
    name
end
""",
                encoding="utf-8",
            )
            (package_directory / "login.hmr").write_text(
                """package Accounts


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
                """package Tools

pub fn normalize(name)
    name
end
""",
                encoding="utf-8",
            )
            (package_directory / "user.hmr").write_text(
                """package Accounts

import tools:
    normalize

fn normalized_name(name)
    normalize(name)
end
""",
                encoding="utf-8",
            )
            (package_directory / "main.hmr").write_text(
                """package Accounts


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
                "package Accounts\n\npub fn name()\n    \"Accounts\"\nend\n",
                encoding="utf-8",
            )
            (application_directory / "helper.hmr").write_text(
                "package Application\n\nimport accounts\n\nfn helper()\n    Accounts.name()\nend\n",
                encoding="utf-8",
            )
            (application_directory / "main.hmr").write_text(
                "package Application\n\nfn main\n"
                "    print(Accounts.name())\nend\n",
                encoding="utf-8",
            )

            interpreter = Interpreter(package_search_paths=[package_root])
            with self.assertRaises(RuntimeHoomerError) as caught_error:
                interpreter.execute_package(application_directory)

        self.assertIn("`Accounts` has not been defined", str(caught_error.exception))

    def test_imports_package_with_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_root = Path(temporary_directory)
            accounts_directory = package_root / "accounts"
            application_directory = package_root / "application"
            accounts_directory.mkdir()
            application_directory.mkdir()
            (accounts_directory / "teacher.hmr").write_text(
                """package Accounts

pub struct Teacher
    name: "",
end
""",
                encoding="utf-8",
            )
            (application_directory / "main.hmr").write_text(
                """package Application

import accounts as TeacherAccount

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

    def test_installed_and_local_packages_can_share_a_declared_name(self) -> None:
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
                'package Accounts\n\npub fn source()\n    "project"\nend\n',
                encoding="utf-8",
            )
            (installed_accounts_directory / "accounts.hmr").write_text(
                'package Accounts\n\npub fn source()\n    "installed"\nend\n',
                encoding="utf-8",
            )
            (application_directory / "main.hmr").write_text(
                """package Application

import accounts as InstalledAccounts
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
                'package Accounts\n\npub fn greeting()\n    "hello"\nend\n',
                encoding="utf-8",
            )
            (application_directory / "main.hmr").write_text(
                """package Application

import kenekoi/accounts

fn main
    print(Accounts.greeting())
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
                'package Accounts\n\npub fn greeting()\n    "hello"\nend\n',
                encoding="utf-8",
            )
            (application_directory / "main.hmr").write_text(
                "package Application\n\nimport accounts\n\nfn main\nend\n",
                encoding="utf-8",
            )

            interpreter = Interpreter(package_search_paths=[project_root])
            with self.assertRaises(RuntimeHoomerError) as caught_error:
                interpreter.execute_package(application_directory)

        rendered_error = str(caught_error.exception)
        self.assertIn("Could not find import `accounts`", rendered_error)
        self.assertIn("`kenekoi/accounts` for the local package", rendered_error)

    def test_package_reflection_lists_public_functions_and_structs(self) -> None:
        interpreter, output = Interpreter.capture_output()
        interpreter.execute_source(
            """package Accounts

pub struct User
    name,
end

pub fn find_user()
    nil
end
""",
            "accounts.hmr",
        )

        interpreter.execute_source(
            """import accounts
package_info = reflection(Accounts)
print(package_info.name)
print(package_info.path)
print(package_info.functions)
print(package_info.structs)
"""
        )

        self.assertEqual(
            output.getvalue(),
            'Accounts\naccounts\n["find_user"]\n["User"]\n',
        )

    def test_package_accepts_inert_constants(self) -> None:
        interpreter, output = Interpreter.capture_output()
        interpreter.execute_source(
            """package Accounts

pub MAX_LOGIN_ATTEMPTS = 5
pub SUPPORTED_PORTS = [3000, 3001]
""",
            "accounts.hmr",
        )

        interpreter.execute_source(
            "import accounts\n"
            "print(Accounts.MAX_LOGIN_ATTEMPTS)\n"
            "print(Accounts.SUPPORTED_PORTS)\n"
        )

        self.assertEqual(output.getvalue(), "5\n[3000, 3001]\n")

    def test_package_rejects_runtime_statements_and_active_constants(self) -> None:
        with self.assertRaises(PackageContentError) as statement_error:
            run_hoomer(
                """package Accounts

print("loading")
""",
                file_name="accounts.hmr",
            )

        self.assertIn("Runtime statement found at package level", str(statement_error.exception))

        with self.assertRaises(PackageContentError) as constant_error:
            run_hoomer(
                """package Accounts

DATABASE = connect()
""",
                file_name="accounts.hmr",
            )

        self.assertIn("constants cannot execute code", str(constant_error.exception))

    def test_package_rejects_duplicate_declarations_across_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "accounts"
            package_directory.mkdir()
            (package_directory / "first.hmr").write_text(
                "package Accounts\n\nfn find_user()\n    nil\nend\n",
                encoding="utf-8",
            )
            (package_directory / "second.hmr").write_text(
                "package Accounts\n\nfn find_user()\n    nil\nend\n",
                encoding="utf-8",
            )

            with self.assertRaises(PackageContentError) as caught_error:
                Interpreter().check_package(package_directory)

        self.assertIn("`find_user` is duplicated", str(caught_error.exception))

    def test_directory_files_must_declare_the_same_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "accounts"
            package_directory.mkdir()
            (package_directory / "user.hmr").write_text(
                "package Accounts\n\nstruct User name end\n",
                encoding="utf-8",
            )
            (package_directory / "invoice.hmr").write_text(
                "package Billing\n\nstruct Invoice total end\n",
                encoding="utf-8",
            )

            with self.assertRaises(PackageContentError) as caught_error:
                Interpreter().check_package(package_directory)

        self.assertIn("must declare the same package", str(caught_error.exception))

    def test_every_package_file_requires_a_package_header(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "accounts"
            package_directory.mkdir()
            (package_directory / "accounts.hmr").write_text(
                "fn find_user()\n    nil\nend\n",
                encoding="utf-8",
            )

            with self.assertRaises(PackageContentError) as caught_error:
                Interpreter().check_package(package_directory)

        self.assertIn(
            "must begin with a package declaration",
            str(caught_error.exception),
        )

    def test_package_name_must_match_its_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "accounts"
            package_directory.mkdir()
            (package_directory / "accounts.hmr").write_text(
                "package Billing\n\nfn invoice()\n    nil\nend\n",
                encoding="utf-8",
            )

            with self.assertRaises(PackageContentError) as caught_error:
                Interpreter().check_package(package_directory)

        self.assertIn(
            "must agree with its directory name",
            str(caught_error.exception),
        )

    def test_main_must_be_callable_without_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "application"
            package_directory.mkdir()
            (package_directory / "main.hmr").write_text(
                "package Application\n\nfn main(name)\n    print(name)\nend\n",
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
                "package First\n\nimport second\n\nfn first()\n    nil\nend\n",
                encoding="utf-8",
            )
            (second_directory / "second.hmr").write_text(
                "package Second\n\nimport first\n\nfn second()\n    nil\nend\n",
                encoding="utf-8",
            )

            interpreter = Interpreter(package_search_paths=[package_root])
            with self.assertRaises(RuntimeHoomerError) as caught_error:
                interpreter.check_package(first_directory)

        self.assertIn("circular import", str(caught_error.exception))
        self.assertIsNone(interpreter.package_registry.get("first"))
        self.assertIsNone(interpreter.package_registry.get("second"))

    def test_private_package_member_requires_pub_outside_its_package(self) -> None:
        interpreter = Interpreter()
        interpreter.execute_source(
            """package Accounts

fn internal_helper()
    "hidden"
end
""",
            "accounts.hmr",
        )

        with self.assertRaises(RuntimeHoomerError) as caught_error:
            interpreter.execute_source("import accounts\nAccounts.internal_helper()\n")

        rendered_error = str(caught_error.exception)
        self.assertIn("private to package", rendered_error)
        self.assertIn("Add `pub`", rendered_error)
