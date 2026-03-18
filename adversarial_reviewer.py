#!/usr/bin/env python3
import os
import json
import subprocess
import sys
from pathlib import Path


def get_gemini_username():
    """Read Gemini's username from agents_config.json."""
    try:
        with open("agents_config.json", "r") as f:
            config = json.load(f)
            return config.get("gemini", {}).get("username", "gemini-agent")
    except Exception:
        return "gemini-agent"


GEMINI_USERNAME = get_gemini_username()


def get_open_prs():
    """List open PRs using gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "pr", "list", "--json", "number,author,title"],
            capture_output=True, text=True, check=True
        )
        return json.loads(result.stdout)
    except Exception as e:
        print(f"Error fetching PRs: {e}")
        return []


def get_pr_diff(pr_number):
    """Get the diff for a PR."""
    try:
        result = subprocess.run(
            ["gh", "pr", "diff", str(pr_number)],
            capture_output=True, text=True, check=True
        )
        return result.stdout
    except Exception as e:
        print(f"Error fetching diff for PR #{pr_number}: {e}")
        return ""


def adversarial_review_llm(diff, title):
    """Perform an LLM-powered adversarial review using Gemini."""
    review_prompt = f"""You are an adversarial security researcher.
Review the following Pull Request diff for security vulnerabilities, malicious intent, and architectural bypasses.
Project Context: Distributed AI mesh (Project Acropolis), NATS hub-and-spoke, Neo4j, Docker, ESP32-S3 with ATECC608B crypto.

PR Title: {title}
Diff:
{diff}

Focus on:
1. Cryptographic bypasses (e.g. verifying against untrusted public keys).
2. Injection vulnerabilities (command injection, SQL injection, template injection).
3. Insecure defaults or hardcoded secrets.
4. Logic flaws in multi-agent coordination.
5. Backdoors or hidden functionality.
6. Missing input validation at system boundaries.

Return ONLY a valid JSON array of findings. Each finding must have: severity (CRITICAL/HIGH/MEDIUM/LOW), title, description.
If no issues found, return an empty array: []
No markdown fences, no explanation — just the JSON array."""

    try:
        import google.generativeai as genai
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            print("  No GEMINI_API_KEY set, falling back to pattern matching.")
            return None
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(review_prompt)
        text = response.text.strip()

        # Parse JSON from response
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:])
        if text.endswith("```"):
            text = "\n".join(text.split("\n")[:-1])
        text = text.strip()

        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1:
            findings = json.loads(text[start:end + 1])
            return [
                {"severity": f.get("severity", "MEDIUM"),
                 "title": f.get("title", "Untitled"),
                 "description": f.get("description", "")}
                for f in findings
            ]
        return []
    except Exception as e:
        print(f"  LLM review failed ({e}), falling back to pattern matching.")
        return None


def adversarial_review_patterns(diff, title):
    """Fallback: pattern-based adversarial review."""
    findings = []

    if "auth_service.py" in diff:
        if "public_key_b64 = payload.get(\"public_key_b64\")" in diff and "public_key.verify" in diff:
            findings.append({
                "severity": "CRITICAL",
                "title": "Untrusted Public Key Verification",
                "description": "The auth service verifies the challenge signature using a public key provided by the requester. This allows any attacker to generate their own key pair and successfully 'authenticate' as any device_id."
            })
        if "challenge" in diff and "now" in diff and "exp" in diff:
            findings.append({
                "severity": "HIGH",
                "title": "Missing Replay Protection",
                "description": "The service verifies a challenge but doesn't appear to track used challenges or nonces. An attacker could potentially replay a valid challenge-response pair."
            })

    if "agents_config.json" in diff:
        findings.append({
            "severity": "MEDIUM",
            "title": "Static Agent Configuration",
            "description": "Agent approver relationships are hardcoded. If an agent account is compromised, the 'approver' can be used to bypass security enforcements without dynamic revocation."
        })

    if "race.py" in diff:
        if "subprocess.run" in diff and "python" in diff:
            findings.append({
                "severity": "MEDIUM",
                "title": "Potential Arbitrary Code Execution",
                "description": "The race framework executes generated code. If one agent is compromised, it could produce malicious code that executes during the validation phase."
            })

    return findings


def adversarial_review(diff, title):
    """Run LLM review with pattern-matching fallback."""
    result = adversarial_review_llm(diff, title)
    if result is not None:
        return result
    return adversarial_review_patterns(diff, title)


def format_review(findings):
    if not findings:
        return "No critical adversarial findings identified."

    report = "**Adversarial Security Review Report**\n\n"
    for f in findings:
        report += f"### [{f['severity']}] {f['title']}\n"
        report += f"{f['description']}\n\n"

    report += "---\n*Review generated by Adversarial Agent*"
    return report


def post_comment(pr_number, comment):
    """Post a comment on the PR."""
    try:
        subprocess.run(
            ["gh", "pr", "comment", str(pr_number), "--body", comment],
            check=True
        )
        print(f"Commented on PR #{pr_number}")
    except Exception as e:
        print(f"Error commenting on PR #{pr_number}: {e}")


def main():
    target_pr = os.getenv("PR_NUMBER")
    if target_pr:
        try:
            result = subprocess.run(
                ["gh", "pr", "view", target_pr, "--json", "number,author,title"],
                capture_output=True, text=True, check=True
            )
            prs = [json.loads(result.stdout)]
        except Exception as e:
            print(f"Error fetching PR #{target_pr}: {e}")
            prs = []
    else:
        prs = get_open_prs()

    for pr in prs:
        author = pr['author']['login']
        if author == GEMINI_USERNAME:
            print(f"Skipping PR #{pr['number']} initiated by {author}")
            continue

        print(f"Reviewing PR #{pr['number']} by {author}: {pr['title']}")
        diff = get_pr_diff(pr['number'])
        findings = adversarial_review(diff, pr['title'])
        report = format_review(findings)
        post_comment(pr['number'], report)


if __name__ == "__main__":
    main()
