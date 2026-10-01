"""CLI characterization cases shared by the tests, the golden refresher and the coverage runner."""
import os
import subprocess
import sys
from pathlib import Path

from fixtures import AMBIGUOUS, API, CONV_A, CONV_B, CONV_EMPTY, ROOT

SCRIPT = ROOT / "claude_tokens.py"
GOLDEN = Path(__file__).resolve().parent / "golden"
DATA = Path(__file__).resolve().parent / "data"
ENV = {"TZ": "UTC", "COLUMNS": "120", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}

# name -> argv; "{P}" is the fixtures projects folder and "{E}" an empty folder. --projects-dir {P} is appended
# unless the case sets its own.
CASES = {
    "help": ["--help"],
    "report_text": [CONV_A],
    "report_json": [CONV_A, "--json"],
    "report_by_path": ["{P}/" + API + "/" + CONV_A + ".jsonl"],
    "report_pricing_unknown_text": [CONV_B],
    "report_pricing_unknown_json": [CONV_B, "--json"],
    "report_no_usage": [CONV_EMPTY],
    "report_custom_pricing": [CONV_B, "--pricing", str(DATA / "pricing.json")],
    "report_bad_pricing": [CONV_B, "--pricing", str(DATA / "bad-pricing.json")],
    "report_context_window": [CONV_A, "--context-window", "1000000"],
    "report_cold_output": [CONV_A, "--cold-summary-output", "500"],
    "error_context_window": [CONV_A, "--context-window", "0"],
    "error_cold_output": [CONV_A, "--cold-summary-output", "-1"],
    "error_ambiguous_id": [AMBIGUOUS],
    "error_unknown_id": ["99999999-9999-4999-8999-999999999999"],
    "totals_text": ["--totals"],
    "totals_json": ["--totals", "--json"],
    "totals_project": ["--totals", "--project", "billing"],
    "totals_custom_pricing": ["--totals", "--pricing", str(DATA / "pricing.json")],
    "totals_bad_pricing": ["--totals", "--pricing", str(DATA / "bad-pricing.json")],
    "totals_empty": ["--totals", "--projects-dir", "{E}"],
    "last_response_text": [CONV_A, "--last-response"],
    "last_response_json": [CONV_A, "--last-response", "--json"],
    "last_response_none": [CONV_EMPTY, "--last-response"],
    "bash_text": [CONV_A, "--bash"],
    "bash_json": [CONV_A, "--bash", "--json"],
    "bash_none": [CONV_B, "--bash"],
    "files_text": [CONV_A, "--files"],
    "files_json": [CONV_A, "--files", "--json"],
    "files_none": [CONV_B, "--files"],
    "content_combined": [CONV_A, "--last-response", "--bash", "--files"],
    "picker_listing": [],
    "picker_project": ["--project", "billing"],
    "picker_no_match": ["--project", "nothing-matches"],
    "picker_empty": ["--projects-dir", "{E}"],
}


def argv_for(name, projects, empty):
    args = [a.replace("{P}", str(projects)).replace("{E}", str(empty)) for a in CASES[name]]
    if "--projects-dir" not in args:
        args += ["--projects-dir", str(projects)]
    return args


def normalize(text, base):
    # base is the temporary folder holding the fixtures; its path changes on every run.
    text = text.replace(str(base), "<FIXTURES>")
    return text.replace("optional arguments:", "options:")


def run(name, base, projects, empty, command=None):
    """Run one case and return its normalized transcript (exit code, stdout, stderr)."""
    command = command or [sys.executable, str(SCRIPT)]
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR",)}
    env.update(ENV)
    done = subprocess.run(command + argv_for(name, projects, empty), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60)
    return normalize(f"--- exit {done.returncode}\n--- stdout\n{done.stdout}--- stderr\n{done.stderr}", base)


def golden_path(name):
    return GOLDEN / f"{name}.txt"
