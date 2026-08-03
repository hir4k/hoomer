# Changelog

## Unreleased

- Recognize braces used by insertion-ordered map literals and `in` membership.
- Treat source directories as packages; `package` declarations are no longer
  language syntax.

## 0.2.0

- Highlight file-scoped `package` declarations without treating them as
  indentation-opening blocks.
- Highlight unquoted slash-separated package paths such as
  `import kenekoi/accounts`.
- Treat every `fn` declaration as a body opened until `end`.

## 0.1.1

- Align TextMate scopes with VS Code's built-in Ruby grammar so themes color
  Hoomer like Ruby.

## 0.1.0

- Add syntax highlighting for Hoomer declarations, control flow, values,
  comments, operators, function calls, and string interpolation.
- Add comment toggling, bracket pairing, word selection, and indentation rules.
