from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from hoomer.tokens import KEYWORD_TOKEN_TYPES


REPOSITORY_ROOT = Path(__file__).parent.parent
EXTENSION_ROOT = REPOSITORY_ROOT / "editors" / "vscode"


class VSCodeExtensionTests(unittest.TestCase):
    def test_hmr_files_are_registered_as_hoomer(self) -> None:
        manifest = self._read_json("package.json")
        language = manifest["contributes"]["languages"][0]

        self.assertEqual(language["id"], "hoomer")
        self.assertIn(".hmr", language["extensions"])

    def test_grammar_covers_every_lexer_keyword(self) -> None:
        grammar = self._read_json("syntaxes/hoomer.tmLanguage.json")
        keyword_patterns = grammar["repository"]["keywords"]["patterns"]
        keyword_expressions = [pattern["match"] for pattern in keyword_patterns]

        missing_keywords = [
            keyword
            for keyword in KEYWORD_TOKEN_TYPES
            if not any(re.fullmatch(expression, keyword) for expression in keyword_expressions)
        ]

        self.assertEqual(missing_keywords, [])

    def test_grammar_regular_expressions_compile(self) -> None:
        grammar = self._read_json("syntaxes/hoomer.tmLanguage.json")
        regular_expressions = self._find_regular_expressions(grammar)

        for expression in regular_expressions:
            with self.subTest(expression=expression):
                re.compile(expression)

    def test_grammar_uses_ruby_compatible_scopes(self) -> None:
        grammar = self._read_json("syntaxes/hoomer.tmLanguage.json")
        scope_names = set(self._find_values_named("name", grammar))
        expected_scopes = {
            "keyword.control.def.ruby",
            "entity.name.function.ruby",
            "keyword.control.class.ruby",
            "entity.name.type.class.ruby",
            "variable.other.constant.ruby",
            "string.quoted.double.interpolated.ruby",
            "meta.embedded.line.ruby",
        }

        self.assertTrue(expected_scopes.issubset(scope_names))

    def test_function_definitions_increase_indentation(self) -> None:
        configuration = self._read_json("language-configuration.json")
        indentation_rules = configuration["indentationRules"]
        increase_indent = re.compile(indentation_rules["increaseIndentPattern"])

        self.assertIsNotNone(increase_indent.match("fn answer()"))
        self.assertIsNotNone(increase_indent.match("pub fn answer()"))
        self.assertIsNotNone(increase_indent.match("fn answer(value: 42)"))

    def test_grammar_highlights_unquoted_package_import_paths(self) -> None:
        grammar = self._read_json("syntaxes/hoomer.tmLanguage.json")
        definition_patterns = grammar["repository"]["definitions"]["patterns"]
        import_pattern = next(
            pattern
            for pattern in definition_patterns
            if pattern.get("name") == "meta.require.ruby"
        )

        match = re.search(import_pattern["match"], "import kenekoi/accounts")

        self.assertIsNotNone(match)
        self.assertEqual(match.group(2), "kenekoi/accounts")

    @staticmethod
    def _read_json(relative_path: str) -> dict[str, object]:
        file_path = EXTENSION_ROOT / relative_path
        return json.loads(file_path.read_text(encoding="utf-8"))

    @classmethod
    def _find_regular_expressions(cls, value: object) -> list[str]:
        if isinstance(value, list):
            return [
                expression
                for item in value
                for expression in cls._find_regular_expressions(item)
            ]
        if not isinstance(value, dict):
            return []

        expressions: list[str] = []
        for key, child_value in value.items():
            is_regular_expression = key in {"begin", "end", "match"}
            if is_regular_expression and isinstance(child_value, str):
                expressions.append(child_value)
                continue
            expressions.extend(cls._find_regular_expressions(child_value))
        return expressions

    @classmethod
    def _find_values_named(cls, name: str, value: object) -> list[str]:
        if isinstance(value, list):
            return [
                found_value
                for item in value
                for found_value in cls._find_values_named(name, item)
            ]
        if not isinstance(value, dict):
            return []

        found_values: list[str] = []
        for key, child_value in value.items():
            if key == name and isinstance(child_value, str):
                found_values.append(child_value)
                continue
            found_values.extend(cls._find_values_named(name, child_value))
        return found_values


if __name__ == "__main__":
    unittest.main()
