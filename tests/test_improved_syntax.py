from __future__ import annotations

from pathlib import Path
import unittest

from hoomer import ast
from hoomer.errors import ParserError, RuntimeHoomerError
from hoomer.interpreter import Interpreter
from hoomer.lexer import Lexer
from hoomer.parser import Parser
from tests.helpers import run_hoomer


class ImprovedSyntaxTests(unittest.TestCase):
    def test_print_accepts_parenthesized_and_parenthesis_free_calls(self) -> None:
        _, output, _ = run_hoomer('print("Hello")\nprint "World"\n')

        self.assertEqual(output, "Hello\nWorld\n")

    def test_ordinary_calls_may_omit_parentheses_when_unambiguous(self) -> None:
        source_code = """fn greet(name, punctuation: = "!")
    "Hello {name}{punctuation}"
end

message = greet "Hirak", punctuation="?"
print message
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "Hello Hirak?\n")

    def test_struct_construction_cannot_omit_parentheses(self) -> None:
        source_code = """struct User name end
User name="Hirak"
"""

        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer(source_code)

        self.assertIn("always requires parentheses", str(caught_error.exception))

    def test_struct_fields_are_comma_separated_and_support_one_line_form(self) -> None:
        source_code = """struct Point x, y end

struct User
    name,
    age=0,
end

point = Point(x=3, y=4)
user = User(name="Hirak")
print point.x + point.y
print user.age
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "7\n0\n")

    def test_struct_required_fields_and_named_only_construction_are_enforced(self) -> None:
        source_code = """struct User
    name,
    age=0,
end

User(age=26)
"""
        with self.assertRaises(RuntimeHoomerError) as missing_field_error:
            run_hoomer(source_code)
        self.assertIn("missing required fields", str(missing_field_error.exception))
        self.assertIn("name", str(missing_field_error.exception))

        positional_source = """struct User name end
User("Hirak")
"""
        with self.assertRaises(RuntimeHoomerError) as positional_error:
            run_hoomer(positional_source)
        self.assertIn("constructed with named fields", str(positional_error.exception))
        self.assertIn("field_name=value", str(positional_error.exception))

    def test_function_parameters_support_all_required_and_optional_forms(self) -> None:
        source_code = """fn describe(
    prefix="Value",
    value:,
    punctuation: = "!",
)
    "{prefix}: {value}{punctuation}"
end

print describe(value="ready")
print describe("Result", value="done", punctuation="?")
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "Value: ready!\nResult: done?\n")

    def test_required_named_parameter_cannot_be_omitted_or_passed_positionally(self) -> None:
        source_code = """fn connect(host:)
    host
end

connect()
"""
        with self.assertRaises(RuntimeHoomerError) as missing_argument_error:
            run_hoomer(source_code)
        self.assertIn("connect(host:)", str(missing_argument_error.exception))

        with self.assertRaises(RuntimeHoomerError):
            run_hoomer("fn connect(host:)\n    host\nend\nconnect(\"localhost\")\n")

    def test_named_call_arguments_must_follow_positional_arguments(self) -> None:
        source_code = """fn create(name, age:)
    name
end

create(age=26, "Hirak")
"""

        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer(source_code)

        self.assertIn(
            "A positional argument cannot follow a named argument",
            str(caught_error.exception),
        )

    def test_parser_records_parameter_roles_without_encoded_markers(self) -> None:
        source_code = """fn connect(retries=3, host:, port: = 5432)
    host
end
"""
        program = Parser(Lexer(source_code, "parameters.hmr").scan_tokens()).parse()
        function = program.statements[0]

        self.assertIsInstance(function, ast.FunctionDefinition)
        self.assertEqual(
            [parameter.name for parameter in function.parameters],
            ["retries", "host", "port"],
        )
        self.assertEqual(
            [parameter.is_named for parameter in function.parameters],
            [False, True, True],
        )
        self.assertIsNotNone(function.parameters[0].default_value)
        self.assertIsNone(function.parameters[1].default_value)
        self.assertIsNotNone(function.parameters[2].default_value)

    def test_positional_parameters_cannot_follow_named_parameters(self) -> None:
        source_code = """fn invalid(host:, retries)
    host
end
"""

        with self.assertRaises(ParserError) as caught_error:
            run_hoomer(source_code)

        self.assertIn(
            "Positional parameters must appear before named parameters",
            str(caught_error.exception),
        )

    def test_qualified_struct_and_literal_patterns_match(self) -> None:
        source_code = """module Accounts
    pub struct User
        name,
        city=nil,
    end
end

user = Accounts.User(name="Hirak", city="Guwahati")

when user as response
    Accounts.User
        print response.name
    _
        print "wrong type"
end

when user.city as city
    "Guwahati"
        print "local match"
    nil
        print "missing"
    _
        print "elsewhere"
end
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "Hirak\nlocal match\n")

    def test_lists_for_loops_and_continue_work_together(self) -> None:
        source_code = """struct User
    name,
    active=true,
end

users = [
    User(name="Hirak"),
    User(name="Hidden", active=false),
    User(name="Rahul"),
]

for user in users
    if user.active == false
        continue
    end
    print user.name
end
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "Hirak\nRahul\n")

    def test_private_module_member_requires_pub(self) -> None:
        source_code = """module Accounts
    fn internal_helper()
        "hidden"
    end
end

Accounts.internal_helper()
"""

        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer(source_code)

        rendered_error = str(caught_error.exception)
        self.assertIn("private to module", rendered_error)
        self.assertIn("Add `pub`", rendered_error)

    def test_complete_accounts_application_example(self) -> None:
        examples_directory = Path(__file__).parents[1] / "examples"
        runner_path = examples_directory / "run_application.hmr"
        expected_output = (
            "Welcome Hirak!\n"
            "ID: 10\n"
            "Name: Hirak\n"
            "Email: hirak@example.com\n"
            "Age: 26\n"
            "City was not provided\n"
            "Hello Hirak!\n"
            "Hi Rahul!\n"
        )

        interpreter, output = Interpreter.capture_output(
            module_search_paths=[examples_directory]
        )
        interpreter.execute_file(runner_path)

        self.assertEqual(output.getvalue(), expected_output)
