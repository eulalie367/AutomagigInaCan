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

_ENV_ALLOWLIST = {
    "NATS_URL", "JWT_SECRET", "SIMULATED", "HF_MODEL",
    "GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION",
}


def load_env():
    """Load .env file from repo root if it exists (allowlisted keys only).

    API keys are NOT loaded — authentication uses CLI login:
      - anthropic: uses ~/.anthropic or SDK default auth
      - gemini: uses gcloud ADC (gcloud auth application-default login)
      - huggingface: uses huggingface-cli login (cached token)
    """
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if key in _ENV_ALLOWLIST and value and value != "your_key_here":
                    os.environ.setdefault(key, value)


load_env()


def _load_stored_credentials():
    """Load credentials from login.py's secure store (~/.config/acropolis/)."""
    cred_dir = Path.home() / ".config" / "acropolis"
    for name, env_keys in [
        ("anthropic.json", ["ANTHROPIC_API_KEY"]),
        ("gemini.json", ["GEMINI_API_KEY", "GOOGLE_API_KEY"]),
    ]:
        cred_file = cred_dir / name
        if cred_file.exists():
            try:
                import json as _json
                data = _json.loads(cred_file.read_text())
                key = data.get("api_key")
                if key:
                    for env_key in env_keys:
                        os.environ.setdefault(env_key, key)
            except Exception:
                pass


_load_stored_credentials()


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


# ── Model callers (login-based auth — no API keys) ───────────────────────────
def call_claude(prompt: str) -> str:
    """Call Claude via Anthropic SDK. Auth: `anthropic` SDK default chain.

    The SDK resolves credentials in order:
      1. ANTHROPIC_API_KEY env var (if set)
      2. ~/.anthropic/auth.json (from `anthropic auth login`)
      3. Keyring / OS credential store
    No explicit key needed if you've run: anthropic auth login
    """
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return _extract_code(msg.content[0].text)


def call_gemini(prompt: str) -> str:
    """Call Gemini via google-genai SDK. Auth: Application Default Credentials.

    Login once with: gcloud auth application-default login
    Or set GOOGLE_CLOUD_PROJECT + run: gcloud auth login
    Falls back to GEMINI_API_KEY/GOOGLE_API_KEY env var if ADC unavailable.
    """
    # Try new google.genai SDK with ADC first
    try:
        from google import genai
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

        if project:
            # Use Vertex AI with ADC (gcloud auth application-default login)
            client = genai.Client(vertexai=True, project=project, location=location)
        else:
            # Try with API key from env as fallback
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if api_key:
                client = genai.Client(api_key=api_key)
            else:
                # Try ADC without explicit project
                client = genai.Client(vertexai=True, project="default", location=location)

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        return _extract_code(response.text)
    except ImportError:
        pass

    # Fallback to deprecated google.generativeai
    import google.generativeai as genai
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
    m = genai.GenerativeModel("gemini-2.0-flash")
    response = m.generate_content(prompt)
    return _extract_code(response.text)


def call_huggingface(prompt: str) -> str:
    """Call HuggingFace via InferenceClient. Auth: cached login token.

    Login once with: huggingface-cli login
    Token is cached in ~/.cache/huggingface/token
    Falls back to HF_TOKEN env var if login not found.
    """
    from huggingface_hub import InferenceClient, get_token
    # get_token() checks: HF_TOKEN env var → cached login token → None
    token = get_token()
    if not token:
        raise RuntimeError(
            "Not authenticated with Hugging Face.\n"
            "Run: huggingface-cli login"
        )
    model = os.environ.get("HF_MODEL", "mistralai/Mistral-7B-Instruct-v0.3")
    client = InferenceClient(model=model, token=token)
    response = client.text_generation(prompt, max_new_tokens=4096)
    return _extract_code(response)


def check_auth():
    """Check authentication status for all providers. Returns dict of status."""
    status = {}

    # Claude / Anthropic
    try:
        import anthropic
        client = anthropic.Anthropic()
        if client.api_key:
            status["claude"] = "authenticated"
        else:
            status["claude"] = "NOT authenticated — run: anthropic auth login"
    except Exception as e:
        status["claude"] = f"NOT authenticated — {e}"

    # Gemini / Google
    try:
        from google import genai
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if project:
            status["gemini"] = f"authenticated (Vertex AI, project={project})"
        elif os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
            status["gemini"] = "authenticated (API key fallback)"
        else:
            status["gemini"] = "NOT authenticated — run: gcloud auth application-default login"
    except ImportError:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if api_key:
            status["gemini"] = "authenticated (API key, legacy SDK)"
        else:
            status["gemini"] = "NOT authenticated — run: gcloud auth application-default login"

    # HuggingFace
    try:
        from huggingface_hub import get_token
        token = get_token()
        if token:
            status["huggingface"] = "authenticated (login token)"
        else:
            status["huggingface"] = "NOT authenticated — run: huggingface-cli login"
    except ImportError:
        status["huggingface"] = "NOT available — pip install huggingface-hub"

    return status


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
    """Run validation command. Uses shell=False to prevent command injection."""
    filepath_str = str(filepath)
    cmd = [
        sys.executable, "-c",
        f"import ast; ast.parse(open({filepath_str!r}).read()); print('SYNTAX OK')"
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10
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
        "huggingface": ("HuggingFace", call_huggingface),
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

        # Round summary — supports 2+ contenders
        if round_data:
            ranked = sorted(
                round_data.items(),
                key=lambda kv: kv[1]["scores"]["total"],
                reverse=True,
            )
            top_score = ranked[0][1]["scores"]["total"]
            leaders = [name for name, rd in ranked if rd["scores"]["total"] == top_score]

            scoreboard = "  vs  ".join(
                f"{rd['label']}: {rd['scores']['total']}pts"
                for _, rd in ranked
            )

            if len(leaders) > 1:
                winner, colour = "TIE", Y
            else:
                winner, colour = round_data[leaders[0]]["label"], G
            print(f"\n  Round {r} → {scoreboard}  →  {_c(winner, colour)}")

            # Show diff between top two contenders
            if len(ranked) >= 2:
                da, db = ranked[0][1], ranked[1][1]
                diff = generate_diff(da["code"], db["code"], da["label"], db["label"])
                if diff:
                    diff_file = REPO_ROOT / "results" / f"diff_{task_id}_r{r}.patch"
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

    if len(totals) >= 2:
        max_score = max(totals.values())
        top = [label for label, score in totals.items() if score == max_score]
        overall = top[0] if len(top) == 1 else "TIE"
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
        model_callers = {"claude", "gemini", "huggingface"}
        print("Detected worktrees:")
        for name, path in worktrees.items():
            mapped = "mapped" if name in model_callers else "no model caller"
            print(f"  {name:15s} -> {path}  ({mapped})")
        print()
        print("Authentication status (login-based, no API keys):")
        auth = check_auth()
        for provider, status in auth.items():
            print(f"  {provider:15s}: {status}")
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
