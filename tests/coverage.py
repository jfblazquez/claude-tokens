#!/usr/bin/env python3
"""Line coverage of the characterization cases, using only the stdlib trace module:

    python3 tests/coverage.py [--min 80] [module.py ...]

Every case runs under `python -m trace --count` accumulating into one counts file; the report then lists the
executed share of each module's executable lines and the lines never run.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from characterization import CASES, ROOT, SCRIPT, run  # noqa: E402
from fixtures import build_projects  # noqa: E402


def cover_stats(cover_file):
    executed, missing = 0, []
    for number, line in enumerate(cover_file.read_text(encoding="utf-8").splitlines(), 1):
        mark = line[:7]
        if mark.startswith(">>>>>>"):
            missing.append(number)
        elif mark.strip().rstrip(":").isdigit():
            executed += 1
    return executed, missing


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("modules", nargs="*", default=[SCRIPT.name])
    parser.add_argument("--min", type=float, default=80.0)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as base:
        projects = build_projects(base)
        empty = Path(base) / "empty"
        empty.mkdir()
        counts, report = Path(base) / "counts", Path(base) / "report"
        # --no-report would skip saving the counts file, so each run writes a throwaway report instead.
        command = [sys.executable, "-m", "trace", "--count", f"--file={counts}", f"--coverdir={Path(base) / 'runs'}",
                   f"--ignore-dir={Path(sys.prefix)}", str(SCRIPT)]
        for name in CASES:
            run(name, base, projects, empty, command=command)
        subprocess.run([sys.executable, "-m", "trace", "--report", "--missing", f"--file={counts}",
                        f"--coverdir={report}"], check=True, cwd=str(ROOT), capture_output=True)
        failed = False
        for module in args.modules:
            matches = sorted(report.glob(Path(module).stem + ".cover")) or sorted(report.glob("*" + Path(module).stem + ".cover"))
            if not matches:
                print(f"{module}: no coverage data")
                failed = True
                continue
            executed, missing = cover_stats(matches[0])
            total = executed + len(missing)
            share = 100 * executed / total if total else 100.0
            print(f"{module}: {share:.1f}% of {total} executable lines ({len(missing)} not run)")
            print("  not run: " + ", ".join(str(n) for n in missing))
            failed |= share < args.min
        sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
