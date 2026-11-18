"""Run the same local quality checks from a monorepo or a standalone API."""

import argparse
import subprocess
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
CHECKS: dict[str, list[str]] = {
    "lint": ["ruff", "check"],
    "format": ["ruff", "format", "--check"],
    "type": ["pyright"],
    "test": ["pytest"],
    "docs": [
        "sphinx-build",
        "-E",
        "-a",
        "-W",
        "--keep-going",
        "-b",
        "html",
        "docs",
        "docs/_build/html",
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=CHECKS)
    arguments = parser.parse_args()
    command = ["uv", "run", "--locked"]
    if arguments.check == "docs":
        command.extend(["--group", "docs"])
    command.extend(CHECKS[arguments.check])
    return subprocess.run(command, cwd=API_ROOT, check=False).returncode  # noqa: S603


if __name__ == "__main__":
    raise SystemExit(main())
