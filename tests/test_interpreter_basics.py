from __future__ import annotations

import unittest

from hoomer.errors import ParserError, RuntimeHoomerError
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


    def test_functions_use_implicit_returns_and_named_default_parameters(self) -> None:
        _, output, _ = run_hoomer(
            """fn greet(name: "World")
    if name == ""
        return "Hello, stranger"
    end
    "Hello, {name}"
end

print greet()
print greet(name: "Hirak")
print greet(name: "")
"""
        )

        self.assertEqual(output, "Hello, World\nHello, Hirak\nHello, stranger\n")

    def test_final_expression_is_returned_automatically(self) -> None:
        _, output, _ = run_hoomer(
            """fn answer()
    42
end

print answer()
"""
        )

        self.assertEqual(output, "42\n")

    def test_if_conditions_require_a_boolean(self) -> None:
        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer(
                """fn user_age()
    return 26
end

if user_age()
    print "adult"
end
"""
            )

        rendered_error = str(caught_error.exception)
        self.assertIn("condition must produce a boolean", rendered_error)
        self.assertIn("Found:\n    number", rendered_error)

    def test_fallible_function_marker_is_runtime_metadata(self) -> None:
        _, _, interpreter = run_hoomer(
            """fn save_user!(user)
    return user
end
"""
        )

        runtime_function = interpreter.global_environment.get_local("save_user!")
        self.assertTrue(runtime_function.is_fallible)

    def test_second_function_definition_is_rejected(self) -> None:
        with self.assertRaises(ParserError) as caught_error:
            run_hoomer(
                """fn greet(name)
    return name
end

fn greet(first_name, last_name)
    return "{first_name} {last_name}"
end
"""
            )

        self.assertIn("already defined", str(caught_error.exception))
        self.assertIn("one definition", str(caught_error.exception))

    def test_function_without_a_value_on_one_path_returns_nil_on_that_path(self) -> None:
        _, output, _ = run_hoomer(
            """fn find_name(found)
    if found
        "Hirak"
    end
end

print find_name(true)
print find_name(false)
"""
        )

        self.assertEqual(output, "Hirak\nnil\n")

    def test_value_returning_function_accepts_complete_if_paths(self) -> None:
        _, output, _ = run_hoomer(
            """fn label(ready)
    if ready
        "ready"
    else
        "waiting"
    end
end

print label(true)
print label(false)
"""
        )

        self.assertEqual(output, "ready\nwaiting\n")

    def test_bare_return_still_returns_nil_early(self) -> None:
        _, output, _ = run_hoomer(
            """fn find_name(found)
    if found
        "Hirak"
    else
        return
    end
end

print find_name(true)
print find_name(false)
"""
        )

        self.assertEqual(output, "Hirak\nnil\n")


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
