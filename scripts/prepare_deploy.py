from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_step(title: str, command: list[str], *, check: bool = True) -> None:
    print()
    print(f"== {title} ==")
    subprocess.run(command, cwd=PROJECT_ROOT, check=check)


def main() -> int:
    python = sys.executable

    try:
        _run_step(
            "Validate deployment config",
            [python, "scripts/validate_setup.py", "--deployment", "--skip-env"],
        )
        _run_step(
            "Compile Python sources",
            [python, "-m", "compileall", "bot", "main.py", "scripts"],
        )
        _run_step(
            "Import application",
            [python, "-c", "import main; print(main.app.title)"],
        )
    except subprocess.CalledProcessError as exc:
        print()
        print(f"Deployment preparation failed with exit code {exc.returncode}.")
        return exc.returncode

    print()
    print("== Git status review ==")
    subprocess.run(["git", "status", "--short"], cwd=PROJECT_ROOT, check=False)

    print()
    print("Deployment preparation completed. Review git diff before committing or pushing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
