from __future__ import annotations

import unittest

from hoomer.errors import RuntimeHoomerError
from tests.helpers import run_hoomer


class InterpreterBasicsTests(unittest.TestCase):
    def test_variables_operators_conditionals_and_interpolation(self) -> None:
        _, output, _ = run_hoomer(
            """name = "Hirak"
score = 5 + 3 * 2

if score > 20
    print "too high"
elsif score == 11
    print "Hello {name}, score: {score}"
else
    print "too low"
end
"""
        )

        self.assertEqual(output, "Hello Hirak, score: 11\n")


    def test_functions_support_automatic_return_explicit_return_and_overloading(self) -> None:
        _, output, _ = run_hoomer(
            """fn greet()
    "Hello"
end

fn greet(name)
    if name == ""
        return "Hello, stranger"
    end
    "Hello, {name}"
end

print greet()
print greet("Hirak")
print greet("")
"""
        )

        self.assertEqual(output, "Hello\nHello, Hirak\nHello, stranger\n")


    def test_predicate_function_must_return_a_boolean(self) -> None:
        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer(
                """fn active?(user)
    "yes"
end

active?(nil)
"""
            )

        self.assertIn("Predicate function `active?`", str(caught_error.exception))
        self.assertIn("instead of a boolean", str(caught_error.exception))

    def test_fallible_function_marker_is_runtime_metadata(self) -> None:
        _, _, interpreter = run_hoomer(
            """fn save_user!(user)
    user
end
"""
        )

        runtime_function = interpreter.global_environment.get_local("save_user!")
        self.assertTrue(runtime_function.is_fallible)

    def test_overloads_with_the_same_arity_are_rejected(self) -> None:
        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer(
                """fn greet(name)
    name
end

fn greet(person)
    person
end
"""
            )

        self.assertIn("overload accepting the same arguments", str(caught_error.exception))


    def test_constants_cannot_be_reassigned(self) -> None:
        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer("MAX_CONNECTIONS = 100\nMAX_CONNECTIONS = 200\n")

        self.assertIn("constant", str(caught_error.exception))
        self.assertIn("MAX_CONNECTIONS", str(caught_error.exception))


    def test_do_block_is_a_function_argument(self) -> None:
        _, output, _ = run_hoomer(
            """fn run(block)
    block()
end

run() do
    print "inside block"
end
"""
        )

        self.assertEqual(output, "inside block\n")


    def test_runtime_errors_use_hoomer_types_and_source_locations(self) -> None:
        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer('total = "two" + 2\n', file_name="types.hmr")

        rendered_error = str(caught_error.exception)
        self.assertIn("types.hmr", rendered_error)
        self.assertIn("line 1, column 15", rendered_error)
        self.assertIn("string and number", rendered_error)
