from __future__ import annotations

from pathlib import Path
import unittest

from hoomer.interpreter import Interpreter


class ExampleProgramTests(unittest.TestCase):
    def test_standalone_examples(self) -> None:
        examples_directory = Path(__file__).parents[1] / "examples"
        expected_outputs = {
            "factorial": (
                "0! = 1\n"
                "1! = 1\n"
                "2! = 2\n"
                "3! = 6\n"
                "4! = 24\n"
                "5! = 120\n"
                "6! = 720\n"
                "7! = 5040\n"
                "8! = 40320\n"
                "9! = 362880\n"
                "10! = 3628800\n"
            ),
            "fibonacci": "0\n1\n1\n2\n3\n5\n8\n13\n21\n34\n55\n89\n",
            "inline_when": (
                "Matched: primary.database.local\n"
                "Without fallback: nil\n"
                "Creating offline connection\n"
                "With fallback: offline\n"
            ),
            "prime_numbers": (
                "Prime numbers up to 50:\n"
                "2\n3\n5\n7\n11\n13\n17\n19\n23\n29\n31\n37\n41\n43\n47\n"
            ),
        }

        for package_name, expected_output in expected_outputs.items():
            with self.subTest(example=package_name):
                interpreter, output = Interpreter.capture_output()
                interpreter.execute_package(examples_directory / package_name)

                self.assertEqual(output.getvalue(), expected_output)

    def test_fizzbuzz_example_counts_from_one_to_one_hundred(self) -> None:
        examples_directory = Path(__file__).parents[1] / "examples"
        interpreter, output = Interpreter.capture_output()

        interpreter.execute_package(examples_directory / "fizz_buzz")

        expected_lines = []
        for number in range(1, 101):
            if number % 15 == 0:
                expected_lines.append("FizzBuzz")
            elif number % 3 == 0:
                expected_lines.append("Fizz")
            elif number % 5 == 0:
                expected_lines.append("Buzz")
            else:
                expected_lines.append(str(number))

        self.assertEqual(output.getvalue().splitlines(), expected_lines)

    def test_checkout_syntax_showcase(self) -> None:
        examples_directory = Path(__file__).parents[1] / "examples"
        showcase_root = examples_directory / "checkout_showcase" / "hoomer"
        showcase_directory = showcase_root / "checkout"
        interpreter, output = Interpreter.capture_output(
            package_search_paths=[showcase_root]
        )

        interpreter.execute_package(showcase_directory)

        self.assertEqual(
            output.getvalue(),
            "------------------------------------------\n"
            "Customer: Hirak <hirak@example.com>\n"
            "Reflected struct: Product ['name', 'price_cents', 'available']\n"
            "Reflected function: checkout! "
            "['customer', 'items', 'coupon_code', 'payment_limit_cents']\n"
            "Audit started: three checkout attempts\n"
            "Approved for Hirak (gold)\n"
            "Subtotal: 3400 cents\n"
            "Discount: 340 cents\n"
            "Charged: 3060 cents\n"
            "Coupon: HUMAN10\n"
            "\n"
            "Not enough Keyboard: requested 3, available 2\n"
            "\n"
            "Payment declined for 11400 cents\n"
            "Audit finished: three checkout attempts\n"
            "Tracking update: day 1\n"
            "Tracking update: day 3\n",
        )

    def test_orm_dsl_example(self) -> None:
        examples_directory = Path(__file__).parents[1] / "examples"
        orm_root = examples_directory / "orm_dsl"
        orm_directory = orm_root / "application"
        interpreter, output = Interpreter.capture_output(
            package_search_paths=[orm_root]
        )

        interpreter.execute_package(orm_directory)

        self.assertEqual(
            output.getvalue(),
            "Model User maps to users\n"
            "Fields: ['name', 'email', 'active']\n"
            "BEGIN\n"
            "Inserted User into users\n"
            "Created: Hirak\n"
            "Model mismatch: users accepts User, not AuditEvent\n"
            "Filtered wrong record: nil\n"
            "COMMIT\n"
            "SELECT * FROM users WHERE active = true LIMIT 10\n",
        )
