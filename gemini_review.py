#!/usr/bin/env python3
"""gemini_review.py — Cross-worktree code reviewer.

Discovers sibling git worktrees and performs lightweight static checks:
  - Python syntax validation via ast.parse
  - Empty file detection
  - Missing shebangs on .sh files
  - TODO/FIXME counts

Prints a summary report to stdout.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path


def discover_worktrees():
    """Parse `git worktree list --porcelain` to find all worktrees."""
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"Warning: could not list worktrees: {exc}", file=sys.stderr)
        return []

    worktrees = []
    current_path = None
    current_branch = None

    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            current_branch = line.split(" ", 1)[1]
        elif line == "":
            if current_path:
                worktrees.append({
                    "path": current_path,
                    "branch": current_branch or "(detached)",
                })
            current_path = None
            current_branch = None

    # Catch the last entry if the output doesn't end with a blank line
    if current_path:
        worktrees.append({
            "path": current_path,
            "branch": current_branch or "(detached)",
        })

    return worktrees


def check_python_syntax(filepath):
    """Return (True, None) if syntax is valid, else (False, error_message)."""
    try:
        source = Path(filepath).read_text(encoding="utf-8", errors="replace")
        ast.parse(source, filename=filepath)
        return True, None
    except SyntaxError as exc:
        return False, f"line {exc.lineno}: {exc.msg}"


def check_shebang(filepath):
    """Return True if the .sh file starts with a shebang line."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            first_line = fh.readline()
        return first_line.startswith("#!")
    except OSError:
        return False


def count_markers(filepath, markers=("TODO", "FIXME")):
    """Count occurrences of TODO/FIXME markers in a file."""
    counts = {m: 0 for m in markers}
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                for marker in markers:
                    if marker in line:
                        counts[marker] += 1
    except OSError:
        pass
    return counts


def review_worktree(worktree):
    """Review a single worktree directory and return a dict of findings."""
    wt_path = Path(worktree["path"])
    findings = {
        "path": str(wt_path),
        "branch": worktree["branch"],
        "python_files": [],
        "shell_files": [],
        "empty_files": [],
        "syntax_errors": [],
        "missing_shebangs": [],
        "marker_counts": {"TODO": 0, "FIXME": 0},
    }

    if not wt_path.is_dir():
        return findings

    for root, _dirs, files in os.walk(wt_path):
        # Skip hidden directories (.git, etc.)
        root_path = Path(root)
        if any(part.startswith(".") for part in root_path.relative_to(wt_path).parts):
            continue

        for fname in files:
            fpath = root_path / fname

            # Empty file check
            try:
                if fpath.stat().st_size == 0:
                    findings["empty_files"].append(str(fpath))
            except OSError:
                continue

            # Python files
            if fname.endswith(".py"):
                findings["python_files"].append(str(fpath))
                ok, err = check_python_syntax(str(fpath))
                if not ok:
                    findings["syntax_errors"].append((str(fpath), err))

            # Shell files
            if fname.endswith(".sh"):
                findings["shell_files"].append(str(fpath))
                if not check_shebang(str(fpath)):
                    findings["missing_shebangs"].append(str(fpath))

            # Marker counts for text-like files
            if fname.endswith((".py", ".sh", ".md", ".txt", ".yml", ".yaml", ".toml")):
                mc = count_markers(str(fpath))
                for k in mc:
                    findings["marker_counts"][k] += mc[k]

    return findings


def print_report(all_findings):
    """Print a human-readable summary report."""
    print("=" * 60)
    print("  Gemini Cross-Worktree Review Report")
    print("=" * 60)
    print()

    for findings in all_findings:
        branch_display = findings["branch"].replace("refs/heads/", "")
        print(f"Worktree: {findings['path']}")
        print(f"  Branch: {branch_display}")
        print(f"  Python files: {len(findings['python_files'])}")
        print(f"  Shell files:  {len(findings['shell_files'])}")

        if findings["empty_files"]:
            print(f"  Empty files ({len(findings['empty_files'])}):")
            for ef in findings["empty_files"]:
                print(f"    - {ef}")

        if findings["syntax_errors"]:
            print(f"  Syntax errors ({len(findings['syntax_errors'])}):")
            for fp, err in findings["syntax_errors"]:
                print(f"    - {fp}: {err}")
        else:
            print("  Syntax errors: none")

        if findings["missing_shebangs"]:
            print(f"  Shell files missing shebang ({len(findings['missing_shebangs'])}):")
            for ms in findings["missing_shebangs"]:
                print(f"    - {ms}")

        todo = findings["marker_counts"]["TODO"]
        fixme = findings["marker_counts"]["FIXME"]
        if todo or fixme:
            print(f"  Markers: {todo} TODO, {fixme} FIXME")

        print()

    print("=" * 60)
    print("  Review complete.")
    print("=" * 60)


if __name__ == "__main__":
    worktrees = discover_worktrees()
    if not worktrees:
        print("No worktrees found. Are you inside a git repository?")
        sys.exit(1)

    all_findings = [review_worktree(wt) for wt in worktrees]
    print_report(all_findings)

    # Exit non-zero if any syntax errors were found
    total_errors = sum(len(f["syntax_errors"]) for f in all_findings)
    if total_errors:
        sys.exit(1)
