#!/usr/bin/env python3
import os
import subprocess
import json
import argparse
import re
from datetime import datetime, timezone
from pathlib import Path

# Reuse existing race logic
from race import (
    call_claude, call_gemini, call_huggingface,
    discover_worktrees, validate_output, basic_score,
    PROJECT_CONTEXT, _extract_code,
)

REPO_ROOT = Path(__file__).parent
RESULTS_DIR = REPO_ROOT / "results"
MICRO_ROOT = REPO_ROOT / "Micro"


def _load_acropolis_context():
    """Build extended context from existing Micro/ services."""
    context_parts = [PROJECT_CONTEXT]

    services_dir = MICRO_ROOT / "services"
    if not services_dir.exists():
        return PROJECT_CONTEXT

    context_parts.append("\n\n--- Existing Acropolis Services ---")

    for service_dir in sorted(services_dir.iterdir()):
        if not service_dir.is_dir():
            continue
        for py_file in service_dir.glob("*.py"):
            try:
                code = py_file.read_text()
                lines = len(code.splitlines())
                context_parts.append(
                    f"\n## {service_dir.name}/{py_file.name} ({lines} lines):\n```python\n{code[:2000]}\n```"
                )
            except OSError:
                pass

    # Include NATS subject mappings
    try:
        from acropolis_bridge import TASK_TO_SERVICE
        context_parts.append("\n\n--- Service Mappings ---")
        for task_id, path in TASK_TO_SERVICE.items():
            context_parts.append(f"  {task_id} -> {path}")
    except ImportError:
        pass

    return "\n".join(context_parts)


def _load_prior_winners():
    """Load winners from the most recent consensus cycle for feedback."""
    consensus_files = sorted(RESULTS_DIR.glob("consensus_*.json"), reverse=True)
    if not consensus_files:
        return None

    try:
        data = json.loads(consensus_files[0].read_text())
        return {
            "timestamp": data.get("timestamp"),
            "winners": data.get("winners", {}),
            "peer_reviews": data.get("peer_reviews", {}),
        }
    except (json.JSONDecodeError, OSError):
        return None


class ConsensusEngine:
    def __init__(self, project_name):
        self.project_name = project_name
        self.worktrees = discover_worktrees()
        self.plans = {}
        self.reviews = {}
        self.unified_plan = ""
        self.execution_results = {}
        self.peer_reviews = {}
        self.winners = {}
        self.acropolis_mode = False

    def _call_agent(self, agent_name, prompt):
        if agent_name == "claude": return call_claude(prompt)
        if agent_name == "gemini": return call_gemini(prompt)
        if agent_name == "huggingface": return call_huggingface(prompt)
        return ""

    def phase_plan(self, objective):
        print(f"--- Phase: Planning for '{objective}' ---")

        context = _load_acropolis_context() if self.acropolis_mode else PROJECT_CONTEXT

        # Load prior cycle feedback for iterative improvement
        prior = _load_prior_winners()
        feedback = ""
        if prior:
            print(f"  Loading feedback from prior cycle ({prior['timestamp']})")
            feedback_parts = ["\n\n--- Prior Cycle Feedback ---"]
            for task_id, info in prior.get("winners", {}).items():
                agent = info.get("agent", "?")
                score = info.get("score", 0)
                feedback_parts.append(f"  {task_id}: won by {agent} (score {score})")
            reviews = prior.get("peer_reviews", {})
            for task_id, task_reviews in reviews.items():
                for reviewer, review in task_reviews.items():
                    issues = review.get("issues", [])
                    if issues:
                        feedback_parts.append(f"  {task_id} issues ({reviewer}):")
                        for issue in issues[:3]:
                            feedback_parts.append(f"    - [{issue.get('severity', '?')}] {issue.get('description', '')}")
            feedback = "\n".join(feedback_parts)

        for agent in ["gemini", "claude"]:
            print(f"  {agent} is drafting a plan...")
            prompt = f"""{context}
{feedback}

Create a detailed technical project plan for: {objective}.
If prior cycle feedback is provided above, address the issues raised and improve on the previous implementation.
Output in Markdown."""
            plan = self._call_agent(agent, prompt)
            self.plans[agent] = plan
            if agent in self.worktrees:
                (Path(self.worktrees[agent]) / "PLAN.md").write_text(plan)

    def phase_verify(self):
        print("--- Phase: Cross-Verification ---")
        print("  Gemini is reviewing Claude's plan...")
        review_prompt = f"Review the following project plan for feasibility and security: \n\n{self.plans['claude']}"
        self.reviews["gemini_on_claude"] = self._call_agent("gemini", review_prompt)

        print("  Claude is reviewing Gemini's plan...")
        review_prompt = f"Review the following project plan for feasibility and security: \n\n{self.plans['gemini']}"
        self.reviews["claude_on_gemini"] = self._call_agent("claude", review_prompt)

    def phase_synthesize(self, objective):
        print("--- Phase: Unified Plan Synthesis ---")
        prompt = f"""Combine the following two plans and their respective peer reviews into a single, unified, and optimized project plan for '{objective}'.

        Plan A (Gemini): {self.plans['gemini']}
        Review of A (Claude): {self.reviews['claude_on_gemini']}

        Plan B (Claude): {self.plans['claude']}
        Review of B (Gemini): {self.reviews['gemini_on_claude']}

        Output the final UNIFIED_PLAN.md content."""

        self.unified_plan = self._call_agent("gemini", prompt)
        Path("UNIFIED_PLAN.md").write_text(self.unified_plan)
        print("  Unified plan saved to UNIFIED_PLAN.md")

    def phase_execute(self):
        print("--- Phase: Execution ---")

        # Extract implementation tasks from the unified plan
        extract_prompt = f"""Given this unified project plan, extract discrete implementation tasks as a JSON array.
Each task should have: task_id (snake_case), filename (python file), description (what to implement).

Plan:
{self.unified_plan}

Return ONLY a valid JSON array, no markdown fences or explanation.
Example: [{{"task_id": "auth_service", "filename": "auth_service.py", "description": "Implement JWT auth..."}}]"""

        print("  Extracting tasks from unified plan...")
        tasks_raw = self._call_agent("gemini", extract_prompt)

        # Parse JSON, retry once if needed
        tasks = self._parse_json_array(tasks_raw)
        if tasks is None:
            print("  Retrying task extraction...")
            retry_prompt = f"Your previous response was not valid JSON. {extract_prompt}"
            tasks_raw = self._call_agent("gemini", retry_prompt)
            tasks = self._parse_json_array(tasks_raw)

        if not tasks:
            print("  ERROR: Could not extract tasks from unified plan.")
            return

        print(f"  Extracted {len(tasks)} tasks")

        # Generate code for each task with each agent
        agents = ["claude", "gemini"]
        for task in tasks:
            task_id = task.get("task_id", "unknown")
            filename = task.get("filename", f"{task_id}.py")
            description = task.get("description", "")

            print(f"\n  Task: {task_id} ({filename})")
            task_results = {}

            context = _load_acropolis_context() if self.acropolis_mode else PROJECT_CONTEXT
            gen_prompt = f"""{context}

Implement the following component:
{description}

Filename: {filename}
Output ONLY the Python file. No explanation."""

            for agent in agents:
                print(f"    {agent} generating...", end=" ", flush=True)
                try:
                    code = self._call_agent(agent, gen_prompt)
                    print(f"{len(code.splitlines())} lines")

                    # Write to worktree
                    if agent in self.worktrees:
                        out_path = Path(self.worktrees[agent]) / "generated" / filename
                        out_path.parent.mkdir(parents=True, exist_ok=True)
                        out_path.write_text(code)
                        validation = validate_output(out_path, "")
                    else:
                        out_path = None
                        validation = {"passed": False, "stdout": "", "stderr": "no worktree"}

                    scores = basic_score(code, validation, ["correctness", "code_quality"])
                    status = "PASS" if validation["passed"] else "FAIL"
                    print(f"    {agent} validation: {status}")

                    task_results[agent] = {
                        "code": code,
                        "validation": validation,
                        "scores": scores,
                        "path": str(out_path) if out_path else None,
                    }
                except Exception as e:
                    print(f"ERROR: {e}")
                    task_results[agent] = {
                        "code": "",
                        "validation": {"passed": False, "stdout": "", "stderr": str(e)},
                        "scores": {"syntax_valid": 0, "total": 0, "loc": 0},
                        "path": None,
                    }

            self.execution_results[task_id] = task_results

    def phase_peer_review(self):
        print("--- Phase: Final Peer Review ---")

        if not self.execution_results:
            print("  No execution results to review.")
            return

        review_prompt_template = """You are reviewing code for a distributed AI mesh system (Project Acropolis).
Review the following code and return your assessment as a JSON object.

Code to review (written by {author}):
```python
{code}
```

Return ONLY valid JSON with this structure:
{{
  "overall_score": <1-10>,
  "categories": {{
    "correctness": <1-10>,
    "security": <1-10>,
    "code_quality": <1-10>,
    "completeness": <1-10>
  }},
  "issues": [
    {{"severity": "critical|high|medium|low", "description": "..."}}
  ],
  "verdict": "approve|request_changes|reject"
}}"""

        for task_id, task_results in self.execution_results.items():
            print(f"\n  Reviewing task: {task_id}")
            task_reviews = {}

            # Claude reviews Gemini's code
            if "gemini" in task_results and task_results["gemini"]["code"]:
                print("    Claude reviewing Gemini's code...")
                prompt = review_prompt_template.format(
                    author="Gemini", code=task_results["gemini"]["code"]
                )
                raw = self._call_agent("claude", prompt)
                review = self._parse_json_object(raw)
                task_reviews["claude_on_gemini"] = review or {"overall_score": 0, "verdict": "reject", "parse_error": True}

            # Gemini reviews Claude's code
            if "claude" in task_results and task_results["claude"]["code"]:
                print("    Gemini reviewing Claude's code...")
                prompt = review_prompt_template.format(
                    author="Claude", code=task_results["claude"]["code"]
                )
                raw = self._call_agent("gemini", prompt)
                review = self._parse_json_object(raw)
                task_reviews["gemini_on_claude"] = review or {"overall_score": 0, "verdict": "reject", "parse_error": True}

            self.peer_reviews[task_id] = task_reviews

            # Determine winner
            claude_score = task_reviews.get("gemini_on_claude", {}).get("overall_score", 0)
            gemini_score = task_reviews.get("claude_on_gemini", {}).get("overall_score", 0)

            if claude_score > gemini_score:
                winner = "claude"
            elif gemini_score > claude_score:
                winner = "gemini"
            else:
                # Tie — use validation status as tiebreaker
                c_valid = task_results.get("claude", {}).get("validation", {}).get("passed", False)
                g_valid = task_results.get("gemini", {}).get("validation", {}).get("passed", False)
                winner = "claude" if c_valid else "gemini" if g_valid else "claude"

            self.winners[task_id] = {
                "agent": winner,
                "score": max(claude_score, gemini_score),
                "code": task_results.get(winner, {}).get("code", ""),
            }
            print(f"    Winner: {winner} (Claude={claude_score}, Gemini={gemini_score})")

        # Integrate winners into Acropolis if enabled
        if self.acropolis_mode:
            self._integrate_winners()

        # Save results
        self._save_results()

    def _parse_json_array(self, text):
        """Extract and parse a JSON array from LLM output."""
        text = text.strip()
        # Strip markdown fences
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])
        text = text.strip()
        # Try to find array bounds
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    def _parse_json_object(self, text):
        """Extract and parse a JSON object from LLM output."""
        text = text.strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])
        text = text.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
        return None

    def _integrate_winners(self):
        """Deploy winning code to Micro/ services via acropolis_bridge."""
        from acropolis_bridge import integrate_winner, validate_integration, TASK_TO_SERVICE

        print("\n--- Phase: Acropolis Integration ---")
        for task_id, winner_info in self.winners.items():
            if task_id not in TASK_TO_SERVICE:
                print(f"  {task_id}: no service mapping, skipping")
                continue

            code = winner_info.get("code", "")
            agent = winner_info.get("agent", "unknown")
            if not code:
                print(f"  {task_id}: no code from winner, skipping")
                continue

            print(f"  Integrating {task_id} (winner: {agent})...", end=" ")
            result = integrate_winner(task_id, code, agent)
            if result.get("success"):
                validation = validate_integration(task_id)
                status = "valid" if validation.get("valid") else f"invalid: {validation.get('error')}"
                print(f"OK ({status})")
            else:
                print(f"FAILED: {result.get('error')}")

    def _save_results(self):
        """Save consensus cycle results to JSON."""
        RESULTS_DIR.mkdir(exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        result_file = RESULTS_DIR / f"consensus_{ts}.json"

        # Build serializable results (exclude raw code from execution_results)
        exec_summary = {}
        for task_id, task_results in self.execution_results.items():
            exec_summary[task_id] = {}
            for agent, data in task_results.items():
                exec_summary[task_id][agent] = {
                    "loc": len(data.get("code", "").splitlines()),
                    "validation_passed": data.get("validation", {}).get("passed", False),
                    "scores": data.get("scores", {}),
                }

        output = {
            "timestamp": ts,
            "project": self.project_name,
            "execution_summary": exec_summary,
            "peer_reviews": self.peer_reviews,
            "winners": {
                tid: {"agent": w["agent"], "score": w["score"]}
                for tid, w in self.winners.items()
            },
        }
        result_file.write_text(json.dumps(output, indent=2))
        print(f"\n  Results saved: {result_file}")


def run_cycle(engine, objective):
    """Run a single consensus cycle."""
    engine.phase_plan(objective)
    engine.phase_verify()
    engine.phase_synthesize(objective)
    engine.phase_execute()
    engine.phase_peer_review()


def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Consensus Engine")
    parser.add_argument("--objective", type=str, required=True, help="Project objective")
    parser.add_argument("--full-cycle", action="store_true", help="Run the entire consensus cycle")
    parser.add_argument("--acropolis", action="store_true", help="Integrate winners into Micro/ services")
    parser.add_argument("--iterations", type=int, default=1,
                        help="Number of consensus cycles (each uses prior cycle's feedback)")
    args = parser.parse_args()

    for i in range(1, args.iterations + 1):
        if args.iterations > 1:
            print(f"\n{'#' * 60}")
            print(f"  CONSENSUS ITERATION {i}/{args.iterations}")
            print(f"{'#' * 60}")

        engine = ConsensusEngine("ProjectAcropolis")
        engine.acropolis_mode = args.acropolis

        if args.full_cycle:
            run_cycle(engine, args.objective)


if __name__ == "__main__":
    main()
