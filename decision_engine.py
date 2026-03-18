import os
import json
import subprocess

def get_unique_features():
    features = {
        "Infrastructure": [".github/workflows/approval_enforcer.yml", "agents_config.json"],
        "Testing": ["test.sh", "tester/orchestrate_tests.py", "race.py"],
        "Content": ["feature_gemini.md", "README.md"]
    }
    present = {}
    for category, files in features.items():
        present[category] = [f for f in files if os.path.exists(f)]
    return present

def deploy_plan(features):
    print("--- 🚀 Minimal Deployment Decision Engine ---")
    print(f"Current detected features: {json.dumps(features, indent=2)}")
    
    plan = [
        "1. Merge branch 'consolidate-all' into 'main' (already contains all features).",
        "2. Push 'main' to origin.",
        "3. Remove all worktrees (alpha, claude, gemini, tester) to unlock branches.",
        "4. Delete all feature branches (alpha, claude, gemini, tester, tester_new, consolidate-all).",
        "5. Final check: Ensure '.github/workflows' is active on 'main'."
    ]
    
    print("\nRecommended Minimal Deployment Strategy:")
    for step in plan:
        print(f"  {step}")

if __name__ == "__main__":
    features = get_unique_features()
    deploy_plan(features)
