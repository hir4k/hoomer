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
    def test_expression_bodied_function_returns_its_expression(self) -> None:
        source_code = """fn add(left, right) = left + right
fn greeting(name="World") = "Hello {name}"

print add(20, 22)
print greeting()
print greeting("Hirak")
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "42\nHello World\nHello Hirak\n")

    def test_expression_bodied_function_is_an_explicit_return_in_the_ast(self) -> None:
        program = Parser(
            Lexer("fn answer() = 42\n", "expression_body.hmr").scan_tokens()
        ).parse()

        function = program.statements[0]
        self.assertIsInstance(function, ast.FunctionDefinition)
        self.assertEqual(len(function.body), 1)
        self.assertIsInstance(function.body[0], ast.ReturnStatement)

    def test_parameterless_block_function_may_omit_parentheses(self) -> None:
        source_code = """fn field(name, field_type)
    print "{name}: {field_type}"
end

fn change
    field "name", "string"
    field "username", "string"
    field "age", "int"
end

change()
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "name: string\nusername: string\nage: int\n")

    def test_public_expression_bodied_function_can_be_called_through_its_package(self) -> None:
        interpreter, output = Interpreter.capture_output()
        interpreter.execute_source(
            """package Numbers

pub fn doubled(number) = number * 2
""",
            "numbers.hmr",
        )
        interpreter.execute_source("import numbers\nprint Numbers.doubled(21)\n")

        self.assertEqual(output.getvalue(), "42\n")

    def test_print_accepts_parenthesized_and_parenthesis_free_calls(self) -> None:
        _, output, _ = run_hoomer('print("Hello")\nprint "World"\n')

        self.assertEqual(output, "Hello\nWorld\n")

    def test_ordinary_calls_may_omit_parentheses_when_unambiguous(self) -> None:
        source_code = """fn greet(name, punctuation: = "!")
    return "Hello {name}{punctuation}"
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
    return "{prefix}: {value}{punctuation}"
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
        interpreter, output = Interpreter.capture_output()
        interpreter.execute_source(
            """package Accounts

pub struct User
    name,
    city=nil,
end
""",
            "accounts.hmr",
        )
        interpreter.execute_source(
            """import accounts

user = Accounts.User(name="Hirak", city="Guwahati")

when user
    Accounts.User as response
        print response.name
    _
        print "wrong type"
end

when user.city
    "Guwahati"
        print "local match"
    nil
        print "missing"
    _
        print "elsewhere"
end
"""
        )

        self.assertEqual(output.getvalue(), "Hirak\nlocal match\n")

    def test_when_is_an_expression_with_branch_specific_bindings(self) -> None:
        source_code = """struct DatabaseConnection
    host,
end

struct DatabaseConnectionFailure
    message,
end

result = DatabaseConnection(host="localhost")
database = when result
    DatabaseConnection as connection
        connection
    DatabaseConnectionFailure as error
        print error.message
        nil
    _
        nil
end

print database.host
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "localhost\n")

    def test_when_requires_a_final_fallback_branch(self) -> None:
        with self.assertRaises(ParserError) as caught_error:
            run_hoomer("""when nil
    nil
        print "nil"
end
""")

        self.assertIn("final `_` branch", str(caught_error.exception))

    def test_inline_when_preserves_a_matching_struct_or_uses_nil(self) -> None:
        source_code = """struct DatabaseConnection host end
struct DatabaseConnectionError message end

fn connect!(should_connect)
    if should_connect
        return DatabaseConnection(host="localhost")
    else
        return DatabaseConnectionError(message="offline")
    end
end

connection = connect!(true) when DatabaseConnection
missing_connection = connect!(false) when DatabaseConnection
print connection.host
print missing_connection
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "localhost\nnil\n")

    def test_inline_when_filters_a_value_stored_in_a_variable(self) -> None:
        source_code = """struct User name end
struct UserError message end

result = UserError(message="missing")
user = result when User
print user
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "nil\n")

    def test_inline_when_uses_an_explicit_fallback_after_a_mismatch(self) -> None:
        source_code = """struct Customer name end
struct CustomerNotFound message end

fn find_customer!()
    return CustomerNotFound(message="missing")
end

customer = find_customer!() when Customer else Customer(name="Guest")
print customer.name
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "Guest\n")

    def test_inline_when_filters_a_parenthesis_free_call_result(self) -> None:
        source_code = """struct User name end
struct UserNotFound id end

fn find_user!(id)
    return UserNotFound(id=id)
end

user = find_user! 10 when User
print user
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "nil\n")

    def test_inline_when_evaluates_its_value_once_and_fallback_lazily(self) -> None:
        source_code = """struct Probe calls=0 end
struct User name end
struct UserError message end

fn find_user!(probe, found)
    probe.calls = probe.calls + 1
    if found
        return User(name="Hirak")
    else
        return UserError(message="missing")
    end
end

fn guest_user(probe)
    probe.calls = probe.calls + 1
    return User(name="Guest")
end

probe = Probe()
found = find_user!(probe, true) when User else guest_user(probe)
print found.name
print probe.calls

missing = find_user!(probe, false) when User else guest_user(probe)
print missing.name
print probe.calls
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "Hirak\n1\nGuest\n3\n")

    def test_inline_when_reuses_qualified_and_literal_patterns(self) -> None:
        interpreter, output = Interpreter.capture_output()
        interpreter.execute_source(
            "package Accounts\n\npub struct User name end\n",
            "accounts.hmr",
        )
        interpreter.execute_source(
            """import accounts

user = Accounts.User(name="Hirak") when Accounts.User
answer = 42 when 42 else 0
wrong_answer = 41 when 42 else 0
print user.name
print answer
print wrong_answer
"""
        )

        self.assertEqual(output.getvalue(), "Hirak\n42\n0\n")

    def test_inline_when_rejects_a_wildcard_pattern(self) -> None:
        with self.assertRaises(ParserError) as caught_error:
            run_hoomer("value = 42 when _\n")

        self.assertIn("would always preserve", str(caught_error.exception))

    def test_fallible_result_must_be_used_or_explicitly_ignored(self) -> None:
        definition = """fn save_user!()
    return nil
end
"""

        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer(definition + "save_user!()\n")

        self.assertIn("result of fallible function", str(caught_error.exception))

        _, _, _ = run_hoomer(definition + "ignore save_user!()\n")

    def test_ignore_rejects_an_ordinary_function(self) -> None:
        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer("""fn save_user()
end

ignore save_user()
""")

        self.assertIn("reserved for deliberately discarded fallible", str(caught_error.exception))

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

    def test_for_loop_supports_inclusive_ascending_and_descending_ranges(self) -> None:
        source_code = """for number in 0..3
    print number
end

for number in 2..0
    print number
end
"""

        _, output, _ = run_hoomer(source_code)

        self.assertEqual(output, "0\n1\n2\n3\n2\n1\n0\n")

    def test_range_bounds_must_be_whole_numbers(self) -> None:
        with self.assertRaises(RuntimeHoomerError) as caught_error:
            run_hoomer("""for number in 0..2.5
    print number
end
""")

        rendered_error = str(caught_error.exception)
        self.assertIn("whole numbers", rendered_error)
        self.assertIn("two integers", rendered_error)

    def test_private_package_member_requires_pub(self) -> None:
        interpreter = Interpreter()
        interpreter.execute_source(
            "package Accounts\n\nfn internal_helper() = \"hidden\"\n",
            "accounts.hmr",
        )

        with self.assertRaises(RuntimeHoomerError) as caught_error:
            interpreter.execute_source("import accounts\nAccounts.internal_helper()\n")

        rendered_error = str(caught_error.exception)
        self.assertIn("private to package", rendered_error)
        self.assertIn("Add `pub`", rendered_error)

    def test_complete_accounts_application_example(self) -> None:
        examples_directory = Path(__file__).parents[1] / "examples"
        application_directory = examples_directory / "application"
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
            package_search_paths=[examples_directory]
        )
        interpreter.execute_package(application_directory)

        self.assertEqual(output.getvalue(), expected_output)
