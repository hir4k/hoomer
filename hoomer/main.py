"""Command-line entry point for running Hoomer files and the interactive REPL."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from hoomer.errors import HoomerError
from hoomer.interpreter import Interpreter
from hoomer.lexer import Lexer
from hoomer.tokens import TokenType


def build_argument_parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(
        prog="hoomer",
        description="Run or check packages written in the human-first Hoomer language.",
    )
    commands = argument_parser.add_subparsers(dest="command", required=True)

    run_command = commands.add_parser("run", help="run a package directory")
    run_command.add_argument("package_directory", type=Path)

    check_command = commands.add_parser("check", help="check a package without running main")
    check_command.add_argument("package_directory", type=Path)

    commands.add_parser("repl", help="start an interactive Hoomer session")
    return argument_parser


def main(arguments: Sequence[str] | None = None) -> int:
    supplied_arguments = list(arguments) if arguments is not None else sys.argv[1:]
    known_commands = {"run", "check", "repl"}
    first_argument_is_package = (
        supplied_arguments
        and supplied_arguments[0] not in known_commands
        and not supplied_arguments[0].startswith("-")
    )
    if first_argument_is_package:
        supplied_arguments.insert(0, "run")

    parsed_arguments = build_argument_parser().parse_args(supplied_arguments)

    if parsed_arguments.command == "repl":
        return run_repl()

    package_directory: Path = parsed_arguments.package_directory
    if package_directory.is_file():
        print(
            "Cannot run an individual package file.\n\n"
            f"{package_directory} belongs to the package directory:\n"
            f"    {package_directory.parent}\n\n"
            "Run:\n"
            f"    hoomer {package_directory.parent}",
            file=sys.stderr,
        )
        return 2
    if not package_directory.is_dir():
        print(f"Hoomer package directory not found: {package_directory}", file=sys.stderr)
        return 2

    interpreter = Interpreter()
    try:
        if parsed_arguments.command == "check":
            interpreter.check_package(package_directory)
        else:
            interpreter.execute_package(package_directory)
    except (HoomerError, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def run_repl() -> int:
    interpreter = Interpreter()
    pending_lines: list[str] = []

    while True:
        prompt = "... " if pending_lines else ">>> "
        try:
            entered_line = input(prompt)
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            pending_lines.clear()
            continue

        if not pending_lines and entered_line.strip() in {"exit", "quit"}:
            return 0

        pending_lines.append(entered_line)
        source_code = "\n".join(pending_lines) + "\n"
        if _source_needs_more_lines(source_code):
            continue

        try:
            interpreter.execute_source(source_code, "<repl>")
        except HoomerError as error:
            print(error, file=sys.stderr)
        finally:
            pending_lines.clear()


def _source_needs_more_lines(source_code: str) -> bool:
    """Identify structurally incomplete REPL input without partially parsing it.

    A parser error such as a missing ``end`` could mean either “the user is still
    typing” or “the submitted program is malformed.” Counting block delimiters
    lets the REPL distinguish those cases. Keywords inside strings and comments
    are already hidden by the lexer, so examples like ``print "end"`` do not
    corrupt the count.
    """

    try:
        tokens = Lexer(source_code, "<repl>").scan_tokens()
    except HoomerError:
        return False

    block_opening_types = {
        TokenType.STRUCT,
        TokenType.FUNCTION,
        TokenType.IF,
        TokenType.WHEN,
        TokenType.DO,
        TokenType.FOR,
        TokenType.WHILE,
    }
    open_block_count = 0
    open_parenthesis_count = 0
    open_bracket_count = 0

    for token_index, token in enumerate(tokens):
        if token.token_type in block_opening_types:
            open_block_count += 1
        elif token.token_type is TokenType.IDENTIFIER and token.lexeme == "error":
            next_index = min(token_index + 1, len(tokens) - 1)
            next_token = tokens[next_index]
            if next_token.token_type is TokenType.IDENTIFIER:
                open_block_count += 1
        elif token.token_type is TokenType.END:
            open_block_count = max(0, open_block_count - 1)
        elif token.token_type is TokenType.LEFT_PARENTHESIS:
            open_parenthesis_count += 1
        elif token.token_type is TokenType.RIGHT_PARENTHESIS:
            open_parenthesis_count = max(0, open_parenthesis_count - 1)
        elif token.token_type is TokenType.LEFT_BRACKET:
            open_bracket_count += 1
        elif token.token_type is TokenType.RIGHT_BRACKET:
            open_bracket_count = max(0, open_bracket_count - 1)

    return (
        open_block_count > 0
        or open_parenthesis_count > 0
        or open_bracket_count > 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
