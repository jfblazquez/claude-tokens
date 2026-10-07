#!/usr/bin/env python3
"""Regenerate the characterization goldens. Run by hand, never from the tests:

    python3 tests/golden/refresh.py [case ...]
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from characterization import CASES, golden_path, run  # noqa: E402
from fixtures import build_projects  # noqa: E402


def main(names):
    unknown = [n for n in names if n not in CASES]
    if unknown:
        sys.exit(f"unknown case(s): {', '.join(unknown)}")
    with tempfile.TemporaryDirectory() as base:
        projects = build_projects(base)
        empty = Path(base) / "empty"
        empty.mkdir()
        for name in names or CASES:
            golden_path(name).write_text(run(name, base, projects, empty), encoding="utf-8")
            print(f"wrote {golden_path(name).name}")


if __name__ == "__main__":
    main(sys.argv[1:])
