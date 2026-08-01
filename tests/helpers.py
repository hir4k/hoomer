from __future__ import annotations

from pathlib import Path

from hoomer.interpreter import Interpreter


def run_hoomer(
    source_code: str,
    *,
    file_name: str = "test.hmr",
    package_search_paths: list[Path] | None = None,
) -> tuple[object, str, Interpreter]:
    interpreter, output = Interpreter.capture_output(
        package_search_paths=package_search_paths
    )
    result = interpreter.execute_source(source_code, file_name)
    return result, output.getvalue(), interpreter
