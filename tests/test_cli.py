from __future__ import annotations

import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from hoomer.main import _source_needs_more_lines, main


class CliTests(unittest.TestCase):
    def test_cli_runs_the_required_example(self) -> None:
        example_path = Path(__file__).parents[1] / "examples" / "user"
        standard_output = io.StringIO()
        standard_error = io.StringIO()

        with contextlib.redirect_stdout(standard_output), contextlib.redirect_stderr(standard_error):
            exit_code = main([str(example_path)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            standard_output.getvalue(),
            "Hello Hirakjyoti Das 😍, from Baruapara\n",
        )
        self.assertEqual(standard_error.getvalue(), "")

    def test_cli_loads_a_package_without_main_silently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "library"
            package_directory.mkdir()
            (package_directory / "library.hmr").write_text(
                "pub fn greeting()\n    \"hello\"\nend\n",
                encoding="utf-8",
            )
            standard_output = io.StringIO()
            standard_error = io.StringIO()

            with (
                contextlib.redirect_stdout(standard_output),
                contextlib.redirect_stderr(standard_error),
            ):
                exit_code = main([str(package_directory)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(standard_output.getvalue(), "")
        self.assertEqual(standard_error.getvalue(), "")

    def test_cli_rejects_an_individual_package_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "hello"
            package_directory.mkdir()
            source_path = package_directory / "main.hmr"
            source_path.write_text(
                "fn main\n    print(\"hello\")\nend\n",
                encoding="utf-8",
            )
            standard_output = io.StringIO()
            standard_error = io.StringIO()

            with (
                contextlib.redirect_stdout(standard_output),
                contextlib.redirect_stderr(standard_error),
            ):
                exit_code = main([str(source_path)])

        self.assertEqual(exit_code, 2)
        self.assertEqual(standard_output.getvalue(), "")
        self.assertIn("Cannot run an individual package file", standard_error.getvalue())
        self.assertIn(f"hoomer {package_directory}", standard_error.getvalue())

    def test_check_validates_without_invoking_main(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            package_directory = Path(temporary_directory) / "hello"
            package_directory.mkdir()
            (package_directory / "main.hmr").write_text(
                "fn main\n    print(\"hello\")\nend\n",
                encoding="utf-8",
            )
            standard_output = io.StringIO()

            with contextlib.redirect_stdout(standard_output):
                exit_code = main(["check", str(package_directory)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(standard_output.getvalue(), "")

    def test_repl_detects_incomplete_blocks_and_parenthesized_calls(self) -> None:
        self.assertTrue(_source_needs_more_lines("fn greet(name)\n"))
        self.assertTrue(_source_needs_more_lines("User(\n"))
        self.assertTrue(_source_needs_more_lines("users = [\n"))
        self.assertTrue(_source_needs_more_lines("for user in users\n"))
        self.assertFalse(_source_needs_more_lines("fn greet(name)\nend\n"))
        self.assertFalse(_source_needs_more_lines('print("end")\n'))
