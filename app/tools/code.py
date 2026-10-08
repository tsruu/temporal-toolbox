# app/tools/code.py

import subprocess
import tempfile
import os
import textwrap
from typing import Dict


class CodeExecutionError(Exception):
    pass


def execute_python_code(
    code: str,
    timeout_seconds: int = 5
) -> Dict[str, str]:
    """
    Executes Python code in an isolated subprocess.

    Returns:
        {
            "stdout": str,
            "stderr": str,
            "status": "success" | "error" | "timeout"
        }
    """

    if not code or not code.strip():
        return {
            "stdout": "",
            "stderr": "Empty code input",
            "status": "error"
        }

    # Normalize indentation (important for LLM-generated code)
    code = textwrap.dedent(code)

    with tempfile.TemporaryDirectory() as tmpdir:
        script_path = os.path.join(tmpdir, "script.py")

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(code)

        try:
            result = subprocess.run(
                ["python", script_path],
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=tmpdir
            )

            status = "success" if result.returncode == 0 else "error"

            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "status": status
            }

        except subprocess.TimeoutExpired as e:
            return {
                "stdout": e.stdout or "",
                "stderr": "Execution timed out",
                "status": "timeout"
            }

        except Exception as e:
            return {
                "stdout": "",
                "stderr": str(e),
                "status": "error"
            }