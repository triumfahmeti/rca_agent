"""Shfaq diagnozat e pasakta për inspektim manual."""
import json
import glob

from evaluate import is_correct, extract_root_cause_section

latest = sorted(glob.glob("results/experiment_*.json"))[-1]
with open(latest, encoding="utf-8") as f:
    results = json.load(f)

for r in results:
    if r["config"] == "A_logs_only":
        continue          # A dështon gjithmonë, s'ka nevojë ta shohim
    if is_correct(r):
        continue

    section = extract_root_cause_section(r.get("diagnosis", ""))
    preview = " ".join(section.split())[:140]
    print(f"[{r['scenario']} / {r['config']}] pritej '{r['ground_truth']}'")
    print(f"   -> {preview}\n")