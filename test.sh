#!/usr/bin/env bash
# test.sh — Gemini worktree test runner
# Validates Python syntax, runs pytest if available, and checks shell scripts.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EXIT_CODE=0

echo "=== Gemini Worktree Test Suite ==="
echo "Running from: $SCRIPT_DIR"
echo ""

# --- 1. Validate Python syntax for all .py files ---
echo "--- Python Syntax Check ---"
PY_FILES=$(find "$SCRIPT_DIR" -name '*.py' -not -path '*/__pycache__/*' 2>/dev/null || true)
if [ -n "$PY_FILES" ]; then
    PY_FAIL=0
    while IFS= read -r pyfile; do
        if python3 -c "import ast, sys; ast.parse(open(sys.argv[1]).read())" "$pyfile" 2>/dev/null; then
            echo "  PASS: $(basename "$pyfile")"
        else
            echo "  FAIL: $(basename "$pyfile")"
            PY_FAIL=1
        fi
    done <<< "$PY_FILES"
    if [ "$PY_FAIL" -ne 0 ]; then
        echo "Python syntax check: FAILED"
        EXIT_CODE=1
    else
        echo "Python syntax check: ALL PASSED"
    fi
else
    echo "  No .py files found — skipping."
fi
echo ""

# --- 2. Run pytest if test files exist ---
echo "--- Pytest ---"
TEST_FILES=$(find "$SCRIPT_DIR" -name 'test_*.py' -o -name '*_test.py' 2>/dev/null || true)
if [ -n "$TEST_FILES" ]; then
    if command -v pytest &>/dev/null; then
        echo "  Found test files, running pytest..."
        if pytest "$SCRIPT_DIR" -v; then
            echo "  pytest: PASSED"
        else
            echo "  pytest: FAILED"
            EXIT_CODE=1
        fi
    else
        echo "  Test files found but pytest is not installed — skipping."
    fi
else
    echo "  No test files found — skipping."
fi
echo ""

# --- 3. Check shell script syntax with bash -n ---
echo "--- Shell Script Syntax Check ---"
SH_FILES=$(find "$SCRIPT_DIR" -name '*.sh' -not -name "$(basename "${BASH_SOURCE[0]}")" 2>/dev/null || true)
# Also check this script itself
ALL_SH="$SCRIPT_DIR/test.sh"
if [ -n "$SH_FILES" ]; then
    ALL_SH="$ALL_SH
$SH_FILES"
fi
SH_FAIL=0
while IFS= read -r shfile; do
    [ -z "$shfile" ] && continue
    if bash -n "$shfile" 2>/dev/null; then
        echo "  PASS: $(basename "$shfile")"
    else
        echo "  FAIL: $(basename "$shfile")"
        SH_FAIL=1
    fi
done <<< "$ALL_SH"
if [ "$SH_FAIL" -ne 0 ]; then
    echo "Shell syntax check: FAILED"
    EXIT_CODE=1
else
    echo "Shell syntax check: ALL PASSED"
fi
echo ""

# --- Summary ---
if [ "$EXIT_CODE" -eq 0 ]; then
    echo "=== All checks passed ==="
else
    echo "=== Some checks failed ==="
fi
exit $EXIT_CODE
