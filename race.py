#!/usr/bin/env python3
"""
Worktree Race — Claude vs Gemini code generation race.

Gives both models the same coding task, writes output to their
respective worktrees, runs validation, and diffs results.

Usage:
    python race.py [--task TASK_ID] [--rounds N] [--list]

Requires: ANTHROPIC_API_KEY, GEMINI_API_KEY (or GOOGLE_API_KEY)
"""

import argparse
import difflib
import json
import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Worktree discovery ────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).parent
WORKTREE_PARENT = REPO_ROOT.parent


def load_env():
    """Load .env file from repo root if it exists."""
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if value and value != "your_key_here":
                    os.environ.setdefault(key, value)


load_env()


def discover_worktrees():
    """Find all git worktrees and return {branch: path} mapping."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True, text=True, cwd=REPO_ROOT
    )
    worktrees = {}
    current_path = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_path = Path(line.split(" ", 1)[1])
        elif line.startswith("branch "):
            branch = line.split("/")[-1]
            if current_path and branch != "main" and branch != "base":
                worktrees[branch] = current_path
    return worktrees


# ── Race tasks ────────────────────────────────────────────────────────────────
PROJECT_CONTEXT = """You are working on Project Acropolis — a distributed AI mesh system.
Stack: Python 3.9, NATS.io (hub-and-spoke), Neo4j, Docker, ESP32-S3 nodes with
ATECC608B crypto co-processors, NVIDIA Jetson AGX Orin (hub), Orange Pi 5 Plus
(API gateway), Khadas VIM4 (inference host), Google Coral USB accelerators.
Services communicate over NATS subjects. All edge devices sign messages with
ATECC608B private keys; the auth-service validates signatures and issues JWTs."""

RACE_TASKS = {
    "auth_service": {
        "name": "Auth Service Implementation",
        "filename": "auth_service.py",
        "prompt": f"""{PROJECT_CONTEXT}

Write a complete Python async auth-service for Project Acropolis.

Requirements:
1. Subscribe to NATS subject `auth.challenge.response`
2. Each message payload is JSON: {{"device_id": str, "public_key_b64": str, "signature_b64": str, "challenge": str}}
3. Verify the ATECC608B signature using the `cryptography` library (ECDSA P-256, SHA-256)
4. If valid, publish a signed JWT to `auth.token.{{device_id}}` with claims: device_id, issued_at, expires_in=3600
5. If invalid, publish {{"error": "invalid_signature"}} to the same subject
6. JWT secret from env var JWT_SECRET, NATS URL from env var NATS_URL
7. No global state mutation inside the message handler
8. Handle malformed JSON without crashing
9. Log each auth attempt to stdout

Output only the Python file. No explanation.""",
        "validate": "python -c \"import ast; ast.parse(open('{file}').read()); print('SYNTAX OK')\"",
        "criteria": ["correctness", "security", "code_quality"],
    },
    "fleet_router": {
        "name": "Fleet Summary Router",
        "filename": "fleet_router.py",
        "prompt": f"""{PROJECT_CONTEXT}

Write a Python async module that:
1. Connects to NATS (url from env NATS_URL, default nats://localhost:4222)
2. Subscribes to `system.discovery.results`
3. On each message: parses JSON, extracts the `fleet` list
4. Publishes a summary to `system.fleet.summary` with:
   {{"count": len(fleet), "online": count_of_online, "offline": count_of_offline, "timestamp": iso_utc}}
5. Also maintains an in-memory dict of device_id -> last_seen
6. Publishes stale device alerts to `system.fleet.stale` if a device hasn't been seen in 30s
7. Include a proper async main() with graceful shutdown on SIGINT/SIGTERM
8. Use only nats-py and stdlib

Output only the Python file. No explanation.""",
        "validate": "python -c \"import ast; ast.parse(open('{file}').read()); print('SYNTAX OK')\"",
        "criteria": ["correctness", "completeness", "code_quality"],
    },
    "task_dag": {
        "name": "Task DAG Engine",
        "filename": "task_dag.py",
        "prompt": f"""{PROJECT_CONTEXT}

Write a Python module implementing a Task DAG (directed acyclic graph) execution engine.

Requirements:
1. Class `TaskDAG` with methods:
   - `add_task(task_id: str, fn: Callable, depends_on: list[str] = None)`
   - `async execute() -> dict[str, Any]` — runs tasks respecting dependencies, max parallelism
   - `validate() -> bool` — checks for cycles using topological sort
   - `get_execution_order() -> list[list[str]]` — returns tasks grouped by execution wave
2. Tasks are async callables that receive a dict of completed dependency results
3. If a task fails, all dependents are skipped (marked as SKIPPED with the error)
4. Results dict maps task_id -> {{"status": "OK"|"FAILED"|"SKIPPED", "result": Any, "duration_ms": float}}
5. Use only asyncio and stdlib
6. Include a `if __name__ == "__main__":` demo with a diamond dependency graph

Output only the Python file. No explanation.""",
        "validate": "python -c \"import ast; ast.parse(open('{file}').read()); print('SYNTAX OK')\"",
        "criteria": ["correctness", "completeness", "code_quality", "design"],
    },
    "nats_handler": {
        "name": "Constrained NATS Handler (speed round)",
        "filename": "nats_handler.py",
        "prompt": f"""{PROJECT_CONTEXT}

Write a Python async function called `make_handler` that returns a NATS message handler.

Hard constraints — violating ANY disqualifies:
- Function signature: `def make_handler(graph, logger)`
- The returned handler must be an `async def` named `handler`
- Must catch `json.JSONDecodeError` and call `logger.warning(f"bad json: {{msg.subject}}")`
- Must catch `Exception` and call `logger.error(f"handler error: {{e}}")` — never re-raise
- Must call `graph.update_hardware(data)` only if parsing succeeds
- Must NOT import anything — assume all names are in scope
- Must be ≤ 20 lines including the outer function
- No type annotations, no docstrings

Output ONLY the function. Zero prose.""",
        "validate": "python -c \"import ast; ast.parse(open('{file}').read()); print('SYNTAX OK')\"",
        "criteria": ["correctness", "instruction_following", "conciseness"],
    },
}


# ── Model callers ─────────────────────────────────────────────────────────────
def call_claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_code(msg.content[0].text)


def call_gemini(prompt: str) -> str:
    import google.generativeai as genai
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY")
    genai.configure(api_key=api_key)
    m = genai.GenerativeModel("gemini-2.0-flash")
    response = m.generate_content(prompt)
    return _extract_code(response.text)


def _extract_code(text: str) -> str:
    """Strip markdown fences if present."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines)


# ── Validation ────────────────────────────────────────────────────────────────
def validate_output(filepath: Path, validate_cmd: str) -> dict:
    """Run validation command and return result."""
    cmd = validate_cmd.format(file=str(filepath))
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        )
        return {
            "passed": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        return {"passed": False, "stdout": "", "stderr": "TIMEOUT"}


# ── Diff ──────────────────────────────────────────────────────────────────────
def generate_diff(code_a: str, code_b: str, label_a: str, label_b: str) -> str:
    diff = difflib.unified_diff(
        code_a.splitlines(keepends=True),
        code_b.splitlines(keepends=True),
        fromfile=label_a,
        tofile=label_b,
    )
    return "".join(diff)


# ── Scoring ───────────────────────────────────────────────────────────────────
def basic_score(code: str, validation: dict, criteria: list) -> dict:
    """Quick heuristic scoring (no API call needed)."""
    scores = {}
    lines = code.strip().splitlines()
    loc = len(lines)

    scores["syntax_valid"] = 10 if validation["passed"] else 0
    scores["loc"] = loc

    # Rough heuristics
    has_error_handling = any("except" in l or "try:" in l for l in lines)
    has_logging = any("log" in l.lower() or "print(" in l for l in lines)
    has_async = any("async " in l for l in lines)
    has_docstrings = any('"""' in l or "'''" in l for l in lines)

    scores["error_handling"] = 1 if has_error_handling else 0
    scores["logging"] = 1 if has_logging else 0
    scores["async_usage"] = 1 if has_async else 0
    scores["documented"] = 1 if has_docstrings else 0
    scores["total"] = scores["syntax_valid"] + sum(
        v for k, v in scores.items()
        if k not in ("syntax_valid", "total", "loc")
    )
    return scores


# ── Colours ───────────────────────────────────────────────────────────────────
G, R, Y, C, B, RST = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[1m", "\033[0m"

def _c(text, colour):
    return f"{colour}{text}{RST}" if sys.stdout.isatty() else text


# ── Main race ─────────────────────────────────────────────────────────────────
def run_race(task_id: str, worktrees: dict, rounds: int = 1):
    task = RACE_TASKS[task_id]
    contenders = {}

    # Map worktree names to model callers
    model_map = {
        "claude": ("Claude", call_claude),
        "gemini": ("Gemini", call_gemini),
    }

    # Filter to worktrees we have callers for
    for wt_name, wt_path in worktrees.items():
        if wt_name in model_map:
            label, caller = model_map[wt_name]
            contenders[wt_name] = {"label": label, "caller": caller, "path": wt_path}

    if len(contenders) < 2:
        available = list(worktrees.keys())
        mapped = [k for k in available if k in model_map]
        print(f"Need at least 2 contenders with model callers. Found worktrees: {available}, mapped: {mapped}")
        sys.exit(1)

    print(f"\n{_c('═' * 60, B)}")
    print(f"{_c('  WORKTREE RACE — Code Generation', B)}")
    print(f"  Task   : {task['name']}")
    print(f"  Rounds : {rounds}")
    print(f"  Racers : {', '.join(c['label'] for c in contenders.values())}")
    print(f"{_c('═' * 60, B)}\n")

    all_results = []

    for r in range(1, rounds + 1):
        print(f"{_c(f'━━ Round {r}/{rounds} ━━', C)}")
        round_data = {}

        for wt_name, info in contenders.items():
            label = info["label"]
            caller = info["caller"]
            wt_path = info["path"]
            out_file = wt_path / task["filename"]

            print(f"  {_c(label, C)}: generating...", end=" ", flush=True)
            t0 = time.time()
            try:
                code = caller(task["prompt"])
                elapsed = time.time() - t0
                print(f"{elapsed:.1f}s ({len(code.splitlines())} lines)")

                # Write to worktree
                out_file.write_text(code)

                # Validate
                validation = validate_output(out_file, task["validate"])
                status = _c("PASS", G) if validation["passed"] else _c("FAIL", R)
                print(f"           validation: {status}")
                if not validation["passed"] and validation["stderr"]:
                    print(f"           error: {validation['stderr'][:120]}")

                scores = basic_score(code, validation, task["criteria"])

                round_data[wt_name] = {
                    "label": label,
                    "code": code,
                    "elapsed": elapsed,
                    "validation": validation,
                    "scores": scores,
                }
            except Exception as e:
                elapsed = time.time() - t0
                print(f"{_c('ERROR', R)}: {e}")
                round_data[wt_name] = {
                    "label": label,
                    "code": "",
                    "elapsed": elapsed,
                    "validation": {"passed": False, "stdout": "", "stderr": str(e)},
                    "scores": {"syntax_valid": 0, "total": 0, "loc": 0},
                }

        # Round summary
        names = list(round_data.keys())
        if len(names) >= 2:
            a, b = names[0], names[1]
            da, db = round_data[a], round_data[b]
            sa, sb = da["scores"]["total"], db["scores"]["total"]
            winner = da["label"] if sa > sb else db["label"] if sb > sa else "TIE"
            colour = G if winner == da["label"] else R if winner == db["label"] else Y
            print(f"\n  Round {r} → {da['label']}: {sa}pts  vs  {db['label']}: {sb}pts  →  {_c(winner, colour)}")

            # Show diff
            diff = generate_diff(da["code"], db["code"], da["label"], db["label"])
            if diff:
                diff_lines = diff.splitlines()
                diff_file = wt_path.parent / "AutomagigInaCan" / "results" / f"diff_{task_id}_r{r}.patch"
                diff_file.parent.mkdir(parents=True, exist_ok=True)
                diff_file.write_text(diff)
                print(f"  Diff saved: {diff_file}")

        all_results.append(round_data)

    # ── Final scoreboard ──────────────────────────────────────────────────────
    print(f"\n{_c('═' * 60, B)}")
    print(f"{_c('  FINAL RESULTS', B)}")
    print(f"{_c('═' * 60, B)}")

    totals = {}
    for wt_name in contenders:
        total = sum(
            rd.get(wt_name, {}).get("scores", {}).get("total", 0)
            for rd in all_results
        )
        label = contenders[wt_name]["label"]
        totals[label] = total
        avg_time = sum(
            rd.get(wt_name, {}).get("elapsed", 0)
            for rd in all_results
        ) / max(len(all_results), 1)
        print(f"  {label:12s}: {total} pts total, {avg_time:.1f}s avg response time")

    labels = list(totals.keys())
    if len(labels) >= 2:
        if totals[labels[0]] > totals[labels[1]]:
            overall = labels[0]
        elif totals[labels[1]] > totals[labels[0]]:
            overall = labels[1]
        else:
            overall = "TIE"
        print(f"\n  {_c('WINNER', B)}: {_c(overall, G)}")

    # Save results
    results_dir = REPO_ROOT / "results"
    results_dir.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    result_file = results_dir / f"race_{task_id}_{ts}.json"

    serializable = {
        "task": task_id,
        "task_name": task["name"],
        "rounds": rounds,
        "timestamp": ts,
        "contenders": {k: v["label"] for k, v in contenders.items()},
        "results": [
            {
                wt: {
                    "label": rd[wt]["label"],
                    "elapsed": rd[wt]["elapsed"],
                    "loc": rd[wt]["scores"]["loc"],
                    "total_score": rd[wt]["scores"]["total"],
                    "syntax_valid": rd[wt]["scores"]["syntax_valid"] > 0,
                }
                for wt in rd
            }
            for rd in all_results
        ],
        "totals": totals,
    }
    result_file.write_text(json.dumps(serializable, indent=2))
    print(f"\n  Results saved: {result_file}")

    # Show worktree file locations
    print(f"\n  Generated code:")
    for wt_name, info in contenders.items():
        f = info["path"] / task["filename"]
        if f.exists():
            print(f"    {info['label']}: {f}")

    print()
    return serializable


def list_tasks():
    print("\nAvailable race tasks:\n")
    for tid, t in RACE_TASKS.items():
        print(f"  {tid:20s}  {t['name']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Worktree code generation race")
    parser.add_argument("--task", type=str, default="auth_service",
                        help="Task ID to race (default: auth_service)")
    parser.add_argument("--rounds", type=int, default=1,
                        help="Number of rounds (default: 1)")
    parser.add_argument("--list", action="store_true",
                        help="List available tasks")
    parser.add_argument("--all", action="store_true",
                        help="Run all tasks")
    args = parser.parse_args()

    if args.list:
        list_tasks()
        worktrees = discover_worktrees()
        print("Detected worktrees:")
        for name, path in worktrees.items():
            mapped = "✓" if name in ("claude", "gemini") else "✗ (no model caller)"
            print(f"  {name:15s} → {path}  {mapped}")
        print()
        sys.exit(0)

    worktrees = discover_worktrees()
    if not worktrees:
        print("No worktrees found (other than main/base). Create them first:")
        print("  ./worktree-create.sh claude")
        print("  ./worktree-create.sh gemini")
        sys.exit(1)

    tasks_to_run = list(RACE_TASKS.keys()) if args.all else [args.task]

    for task_id in tasks_to_run:
        if task_id not in RACE_TASKS:
            print(f"Unknown task: {task_id}")
            list_tasks()
            sys.exit(1)
        run_race(task_id, worktrees, rounds=args.rounds)


if __name__ == "__main__":
    main()
