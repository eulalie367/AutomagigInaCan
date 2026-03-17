# Gemini Worktree

This is the **gemini** worktree of the [AutomagigInaCan](https://github.com/your-org/AutomagigInaCan) project — a multi-agent code generation race framework where Claude and Gemini compete to produce and improve code on parallel branches.

## Purpose

The gemini branch is one side of the competition. Code generated here is reviewed by the gatekeeper (on the main branch) against contributions from the Claude worktree. Each agent works independently, and a scoring/review system evaluates quality, correctness, and coverage.

This worktree currently contains:

- **auth_service.py** — ATECC608B-based device authentication service for the Project Acropolis edge mesh. Subscribes to NATS `auth.challenge.response`, verifies ECDSA P-256 signatures, and issues JWTs.
- **gemini_review.py** — Cross-worktree code reviewer. Discovers sibling worktrees and checks Python syntax, empty files, missing shebangs, and TODO/FIXME counts.
- **test.sh** — Test runner that validates Python syntax, runs pytest, and checks shell script syntax.

## Usage

### Run tests

```bash
bash test.sh
```

### Run the cross-worktree review

```bash
python3 gemini_review.py
```

### Run the auth service (requires NATS and dependencies)

```bash
export JWT_SECRET="your-secret-here"
export NATS_URL="nats://localhost:4222"
pip install nats-py PyJWT cryptography
python3 auth_service.py
```

## How the Race Works

1. Each agent (Claude, Gemini) works on its own git worktree/branch.
2. Agents generate or improve code independently.
3. The gatekeeper reviews both branches, scores contributions, and merges winning code.
4. The cycle repeats, driving iterative improvement across the project.
