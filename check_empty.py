"""Numëron diagnozat me seksionin 'Shkaku rrënjësor' bosh në çdo raund."""
import json
import glob

from evaluate import extract_root_cause_section

for f in sorted(glob.glob("results/experiment_*.json")):
    with open(f, encoding="utf-8") as fh:
        data = json.load(fh)
    data = [r for r in data if r.get("status") != "exception"]

    empty = [
        r for r in data
        if not extract_root_cause_section(r.get("diagnosis") or "").strip()
    ]

    print(f"\n{f}: {len(empty)} bosh nga {len(data)}")
    for r in empty:
        print(f"   {r['scenario']} / {r['config']} / prova {r['trial']} / status: {r['status']}")