from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hoomer.errors import ParserError, RuntimeHoomerError
from hoomer.interpreter import Interpreter
from hoomer.lexer import Lexer
from hoomer.parser import Parser
from tests.helpers import run_hoomer


class LanguageRevisionTests(unittest.TestCase):
    def test_when_uses_visible_branch_delimiters(self) -> None:
        _, output, _ = run_hoomer(
            """
when 42
    42:
        print("matched")
    else:
        print("missed")
end
"""
        )

        self.assertEqual(output, "matched\n")

        with self.assertRaises(ParserError) as caught_error:
            Parser(
                Lexer("when 1\n    1\n        1\n    else:\n        2\nend\n").scan_tokens()
            ).parse()

        self.assertIn("must end with `:`", str(caught_error.exception))

    def test_boolean_operators_are_strict_and_short_circuit(self) -> None:
        _, output, _ = run_hoomer(
            """
fn touched()
    print("called")
    true
end

print(false and touched())
print(true or touched())
print(not false)
"""
        )

        self.assertEqual(output, "false\ntrue\ntrue\n")

        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer("1 and true\n")

        self.assertIn("must be a boolean", str(caught_error.exception))

    def test_is_checks_exact_runtime_types(self) -> None:
        _, output, _ = run_hoomer(
            """
struct User
    name,
end

user = User(name: "Hirak")
print(user is User)
print(1 is Int)
print(1 is not Float)
print(true is Int)
"""
        )

        self.assertEqual(output, "true\ntrue\ntrue\nfalse\n")

    def test_parameterized_do_block_and_function_block_reference(self) -> None:
        _, output, _ = run_hoomer(
            """
fn visit(value, &action)
    action(value, 1)
end

fn show(value, index)
    print("{index}: {value}")
end

visit("inline") do(value, index)
    print("{index}: {value}")
end
visit("named", &show)
"""
        )

        self.assertEqual(output, "1: inline\n1: named\n")

    def test_try_propagates_error_values_with_a_trace(self) -> None:
        result, output, _ = run_hoomer(
            """
error MissingUser
    message,
end

fn find_user!()
    MissingUser(message: "not found")
end

fn load_user!()
    try find_user!()
end

result = load_user!()
when result
    MissingUser as error:
        print(error.message)
        error
    else:
        print("unexpected")
end
""",
            file_name="errors.hmr",
        )

        self.assertEqual(output, "not found\n")
        traced_functions = [frame.function_name for frame in result.error_trace]
        self.assertIn("find_user!", traced_functions)
        self.assertIn("load_user!", traced_functions)

    def test_try_requires_a_fallible_caller_and_callee(self) -> None:
        with self.assertRaises(RuntimeHoomerError) as caller_error:
            run_hoomer(
                """error Problem
end
fn fail!()
    Problem()
end
fn ordinary()
    try fail!()
end
ordinary()
"""
            )

        self.assertIn("inside a function whose name ends in `!`", str(caller_error.exception))

        with self.assertRaises(RuntimeHoomerError) as callee_error:
            run_hoomer(
                """fn ordinary()
    1
end
fn wrong!()
    try ordinary()
end
result = wrong!()
"""
            )

        self.assertIn("only call a fallible function", str(callee_error.exception))

    def test_list_access_assignment_membership_and_while(self) -> None:
        _, output, _ = run_hoomer(
            """
values = [1, 2, 3]
values[1] = 8
index = 0
while index < 3
    if values[index] == 8
        print("eight")
    end
    index = index + 1
end
print(8 in values)
print("oo" in "hoomer")
print([true] == [1])
"""
        )

        self.assertEqual(output, "eight\ntrue\ntrue\nfalse\n")

    def test_if_expression_modulo_and_break(self) -> None:
        _, output, _ = run_hoomer(
            """
label = if 5 % 2 == 1
    "odd"
else
    "even"
end

while true
    print(label)
    break
end
"""
        )

        self.assertEqual(output, "odd\n")

    def test_builtin_reflection_exposes_types_and_field_values(self) -> None:
        _, output, _ = run_hoomer(
            """
struct User
    name,
end

info = reflection(User(name: "Hirak"))
print(info.values["name"])
print(reflection(42).type)
print(reflection(Int).kind)
"""
        )

        self.assertEqual(output, "Hirak\nInt\nprimitive\n")

    def test_reflection_can_load_get_set_and_call_dynamically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            package_directory = root / "greeter"
            package_directory.mkdir()
            (package_directory / "greeter.hmr").write_text(
                """package Greeter

pub fn greet(name)
    "Hello {name}"
end
""",
                encoding="utf-8",
            )

            _, output, _ = run_hoomer(
                """
struct User
    name,
end

user = User(name: "Before")
reflection_set(user, "name", "After")
print(reflection_get(user, "name"))

loaded_package = reflection_load("greeter")
greet = reflection_get(loaded_package, "greet")
message = reflection_call(greet, arguments: ["Hirak"])
print(message)
""",
                package_search_paths=[root],
            )

            self.assertEqual(output, "After\nHello Hirak\n")

    def test_print_is_part_of_the_language_core(self) -> None:
        _, output, _ = run_hoomer('print("available without an import")\n')

        self.assertEqual(output, "available without an import\n")

    def test_nonfallible_function_cannot_return_a_declared_error(self) -> None:
        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer(
                """error Problem
end

fn wrong()
    Problem()
end

value = wrong()
"""
            )

        self.assertIn("name does not end in `!`", str(caught_error.exception))

    def test_public_constants_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            package_directory = root / "settings"
            package_directory.mkdir()
            (package_directory / "settings.hmr").write_text(
                """package Settings

pub PUBLIC_VALUE = 42
PRIVATE_VALUE = 7
""",
                encoding="utf-8",
            )

            _, output, _ = run_hoomer(
                "import settings\nprint(Settings.PUBLIC_VALUE)\n",
                package_search_paths=[root],
            )

            self.assertEqual(output, "42\n")

            with self.assertRaises(RuntimeHoomerError) as private_error:
                run_hoomer(
                    "import settings\nvalue = Settings.PRIVATE_VALUE\n",
                    package_search_paths=[root],
                )

            self.assertIn("private to package", str(private_error.exception))


if __name__ == "__main__":
    unittest.main()
