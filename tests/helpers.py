from __future__ import annotations

from pathlib import Path

from hoomer.interpreter import Interpreter


def run_hoomer(
    source_code: str,
    *,
    file_name: str = "test.hmr",
    module_search_paths: list[Path] | None = None,
) -> tuple[object, str, Interpreter]:
    interpreter, output = Interpreter.capture_output(
        module_search_paths=module_search_paths
    )
    result = interpreter.execute_source(source_code, file_name)
    return result, output.getvalue(), interpreter

