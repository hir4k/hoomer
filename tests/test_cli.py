from __future__ import annotations

import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from hoomer.main import _source_needs_more_lines, main


class CliTests(unittest.TestCase):
    def test_cli_runs_the_required_example(self) -> None:
        example_path = Path(__file__).parents[1] / "examples" / "user.hmr"
        standard_output = io.StringIO()
        standard_error = io.StringIO()

        with contextlib.redirect_stdout(standard_output), contextlib.redirect_stderr(standard_error):
            exit_code = main(["run", str(example_path)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            standard_output.getvalue(),
            "Hello Hirakjyoti Das 😍, from Baruapara\n",
        )
        self.assertEqual(standard_error.getvalue(), "")

    def test_cli_executes_top_level_code_without_an_entry_function(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_path = Path(temporary_directory) / "hello.hmr"
            source_path.write_text('print "hello"\n', encoding="utf-8")
            standard_output = io.StringIO()
            standard_error = io.StringIO()

            with (
                contextlib.redirect_stdout(standard_output),
                contextlib.redirect_stderr(standard_error),
            ):
                exit_code = main(["run", str(source_path)])

        self.assertEqual(exit_code, 0)
        self.assertEqual(standard_output.getvalue(), "hello\n")
        self.assertEqual(standard_error.getvalue(), "")


    def test_repl_detects_incomplete_blocks_and_parenthesized_calls(self) -> None:
        self.assertTrue(_source_needs_more_lines("fn greet(name)\n"))
        self.assertTrue(_source_needs_more_lines("User(\n"))
        self.assertTrue(_source_needs_more_lines("users = [\n"))
        self.assertTrue(_source_needs_more_lines("for user in users\n"))
        self.assertFalse(_source_needs_more_lines("fn greet(name)\nend\n"))
        self.assertFalse(_source_needs_more_lines('print "end"\n'))
