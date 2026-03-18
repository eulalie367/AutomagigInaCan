#!/usr/bin/env python3
"""Acropolis Bridge — connects race/consensus system to Micro/ services
and provides an Aider-style autonomous improvement loop.

Two modes:
  1. Integration: maps race task winners to Micro/ service paths
  2. Autonomous: runs consensus-driven improvement cycles with auto-commit
"""
import argparse
import ast
import json
import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent
MICRO_ROOT = REPO_ROOT / "Micro"

# ── Service integration mappings ─────────────────────────────────────────────
TASK_TO_SERVICE = {
    "auth_service": "Micro/services/auth/auth_service.py",
    "fleet_router": "Micro/services/fleet-router/fleet_router.py",
    "task_dag": "Micro/services/task-dag/task_dag.py",
    "nats_handler": "Micro/services/system-graph/nats_handler.py",
}

_STDLIB = {
    "asyncio", "base64", "json", "os", "sys", "time", "signal",
    "pathlib", "subprocess", "argparse", "collections", "datetime",
    "functools", "hashlib", "hmac", "logging", "re", "struct",
    "threading", "typing", "uuid", "abc", "dataclasses", "enum",
    "contextlib", "io", "math", "secrets", "textwrap", "traceback",
}

_IMPORT_TO_PACKAGE = {
    "nats": "nats-py>=2.6.0",
    "jwt": "PyJWT>=2.8.0",
    "cryptography": "cryptography>=41.0.0",
    "neo4j": "neo4j>=5.0.0",
    "serial": "pyserial>=3.5",
    "huggingface_hub": "huggingface-hub>=0.20.0",
    "google": "google-genai>=1.0.0",
    "anthropic": "anthropic>=0.18.0",
}

DOCKERFILE_TEMPLATE = """FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "{entry_point}"]
"""


# ── Integration functions ────────────────────────────────────────────────────
def extract_imports(code):
    """Extract top-level import names from Python source code."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return imports


def generate_requirements(code):
    """Generate requirements.txt content from code imports."""
    imports = extract_imports(code)
    packages = []
    for imp in sorted(imports):
        if imp in _STDLIB:
            continue
        pkg = _IMPORT_TO_PACKAGE.get(imp)
        if pkg:
            packages.append(pkg)
        elif imp not in _STDLIB:
            packages.append(imp)
    return "\n".join(packages) + "\n" if packages else ""


def integrate_winner(task_id, code, source_agent):
    """Copy winning code to the correct Acropolis service path."""
    if task_id not in TASK_TO_SERVICE:
        return {"success": False, "error": f"Unknown task_id: {task_id}"}

    service_path = REPO_ROOT / TASK_TO_SERVICE[task_id]
    service_dir = service_path.parent
    service_dir.mkdir(parents=True, exist_ok=True)

    service_path.write_text(code)

    reqs = generate_requirements(code)
    reqs_path = service_dir / "requirements.txt"
    reqs_path.write_text(reqs)

    entry_point = service_path.name
    dockerfile_path = service_dir / "Dockerfile"
    dockerfile_path.write_text(DOCKERFILE_TEMPLATE.format(entry_point=entry_point))

    return {
        "success": True,
        "task_id": task_id,
        "source_agent": source_agent,
        "service_path": str(service_path),
    }


def validate_integration(task_id):
    """Validate that an integrated service has valid syntax and structure."""
    if task_id not in TASK_TO_SERVICE:
        return {"valid": False, "error": f"Unknown task_id: {task_id}"}

    service_path = REPO_ROOT / TASK_TO_SERVICE[task_id]
    if not service_path.exists():
        return {"valid": False, "error": f"Service file not found: {service_path}"}

    code = service_path.read_text()
    try:
        ast.parse(code)
    except SyntaxError as e:
        return {"valid": False, "error": f"Syntax error: {e}"}

    dockerfile = service_path.parent / "Dockerfile"
    if not dockerfile.exists():
        return {"valid": False, "error": "Missing Dockerfile"}

    reqs = service_path.parent / "requirements.txt"
    if not reqs.exists():
        return {"valid": False, "error": "Missing requirements.txt"}

    return {"valid": True, "task_id": task_id, "service_path": str(service_path),
            "loc": len(code.splitlines())}


def list_services():
    """List all known service mappings and their current status."""
    for task_id, rel_path in TASK_TO_SERVICE.items():
        path = REPO_ROOT / rel_path
        exists = path.exists()
        loc = len(path.read_text().splitlines()) if exists else 0
        status = f"{loc} lines" if exists else "not created"
        print(f"  {task_id:20s} -> {rel_path:45s} [{status}]")


# ── Autonomous improvement (Aider-style) ─────────────────────────────────────
class AcropolisBridge:
    def __init__(self, target_file=None):
        from consensus_engine import ConsensusEngine
        self.engine = ConsensusEngine("Project Acropolis")
        self.target_file = target_file
        self.repo_root = REPO_ROOT
        self.history_file = self.repo_root / "acropolis_history.json"

    def generate_repo_map(self):
        """Generates a compressed map of the project for LLM context."""
        map_text = "Project Acropolis — Repository Map:\n"
        for p in self.repo_root.glob("**/*.py"):
            if ".venv" in str(p) or "__pycache__" in str(p):
                continue
            rel = p.relative_to(self.repo_root)
            map_text += f"  {rel}\n"
        return map_text

    def commit_change(self, message):
        """Auto-commit changes if they pass verification."""
        try:
            subprocess.run(["git", "add", "."], check=True, cwd=self.repo_root)
            subprocess.run(
                ["git", "commit", "-m", f"Acropolis: {message}"],
                check=True, cwd=self.repo_root,
            )
            print(f"Committed: {message}")
        except subprocess.CalledProcessError as e:
            print(f"Git commit failed: {e}")

    def improve(self, objective):
        """Run a consensus-driven improvement cycle."""
        print(f"\nIMPROVING: {objective}")
        repo_map = self.generate_repo_map()

        full_objective = f"{objective}\n\n{repo_map}"
        self.engine.phase_plan(full_objective)
        self.engine.phase_verify()
        self.engine.phase_synthesize(objective)

        print("Applying synthesized improvements...")
        self.engine.phase_execute()
        self.engine.phase_peer_review()

        print("Running verification tests...")
        test_result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
            capture_output=True, text=True, cwd=self.repo_root,
        )

        if test_result.returncode == 0:
            print("Verification PASSED.")
            self.commit_change(objective)
        else:
            print("Verification FAILED.")
            print(test_result.stdout[-500:] if test_result.stdout else "")


def main():
    parser = argparse.ArgumentParser(description="Acropolis Bridge")
    parser.add_argument("--list", action="store_true", help="List service mappings")
    parser.add_argument("--validate", type=str, help="Validate a task integration")
    parser.add_argument("--improve", type=str, help="Run autonomous improvement cycle")
    parser.add_argument("--file", type=str, help="Target file for focused improvement")
    args = parser.parse_args()

    if args.list:
        list_services()
    elif args.validate:
        result = validate_integration(args.validate)
        print(json.dumps(result, indent=2))
    elif args.improve:
        bridge = AcropolisBridge(args.file)
        bridge.improve(args.improve)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
