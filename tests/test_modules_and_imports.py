from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hoomer.errors import ModuleContentError
from hoomer.interpreter import Interpreter
from tests.helpers import run_hoomer


class ModulesAndImportsTests(unittest.TestCase):
    def test_module_functions_are_available_through_the_namespace(self) -> None:
        _, output, _ = run_hoomer(
            """module Accounts
    pub fn login()
        "logged in"
    end

    pub fn logout()
        "logged out"
    end
end

print Accounts.login()
print Accounts.logout()
"""
        )
        self.assertEqual(output, "logged in\nlogged out\n")


    def test_imports_module_member_with_alias_from_hmr_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            (temporary_path / "Accounts.hmr").write_text(
                """module Accounts
    pub struct Teacher
        name="",
    end
end
""",
                encoding="utf-8",
            )
            application_source = """module Application
    import Accounts.Teacher as TeacherAccount

    pub fn show_teacher()
        teacher = TeacherAccount(name="Hirak")
        print teacher.name
    end
end

Application.show_teacher()
"""

            _, output, _ = run_hoomer(
                application_source,
                module_search_paths=[temporary_path],
            )

        self.assertEqual(output, "Hirak\n")


    def test_selected_imports_resolve_native_text_functions(self) -> None:
        _, output, _ = run_hoomer(
            """module Application
    import Text:
        trim,
        lowercase

    pub fn show_cleaned_name()
        cleaned_name = trim("  HIRAK  ")
        print lowercase(cleaned_name)
    end
end

Application.show_cleaned_name()
"""
        )

        self.assertEqual(output, "hirak\n")


    def test_module_reflection_lists_functions_and_structs(self) -> None:
        _, output, _ = run_hoomer(
            """module Accounts
    pub struct User
        name,
    end
    pub fn find_user()
        nil
    end
end

module_info = reflect(Accounts)
print module_info.functions
print module_info.structs
"""
        )

        self.assertEqual(output, "['find_user']\n['User']\n")

    def test_module_accepts_imports_constants_structs_and_functions(self) -> None:
        source_code = """module Accounts
    import Text:
        trim

    MAX_LOGIN_ATTEMPTS = 5

    struct User
        name="",
        email="",
    end

    fn create_user(name, email)
        User(name=trim(name), email=email)
    end
end

print Accounts.MAX_LOGIN_ATTEMPTS
"""

        _, output, interpreter = run_hoomer(source_code)

        self.assertEqual(output, "5\n")
        accounts_module = interpreter.module_registry.get(["Accounts"])
        self.assertIsNotNone(accounts_module)
        self.assertEqual(
            accounts_module.environment.get_local("MAX_LOGIN_ATTEMPTS"),
            5,
        )

    def test_module_rejects_variable_assignment_as_a_runtime_statement(self) -> None:
        source_code = """module Accounts
    MAX_LOGIN_ATTEMPTS = 5

    user = User(name="Hirak")
end
"""
        interpreter = Interpreter()

        with self.assertRaises(ModuleContentError) as caught_error:
            interpreter.execute_source(source_code, "Accounts.hmr")

        rendered_error = str(caught_error.exception)
        self.assertIn("Hoomer Error in Accounts.hmr at line 4, column 10", rendered_error)
        self.assertIn("Runtime statement found at module level.", rendered_error)
        self.assertIn(
            "Modules can only contain:\n"
            "    import\n"
            "    constant\n"
            "    struct\n"
            "    function",
            rendered_error,
        )
        self.assertIn("Move this code inside a function.", rendered_error)

        # Parsing completes before evaluation begins. Even though the constant
        # appears before the invalid action, no half-loaded Accounts module is
        # left behind after the error.
        self.assertIsNone(interpreter.module_registry.get(["Accounts"]))

    def test_module_rejects_print_but_allows_print_inside_a_function(self) -> None:
        invalid_source = """module Accounts
    print "loading"
end
"""
        with self.assertRaises(ModuleContentError):
            run_hoomer(invalid_source)

        valid_source = """module Accounts
    pub fn show_name(name)
        print name
    end
end

Accounts.show_name("Hirak")
"""
        _, output, _ = run_hoomer(valid_source)
        self.assertEqual(output, "Hirak\n")
