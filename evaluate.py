"""
Vlerëson automatikisht rezultatet e eksperimentit.

Metrika kryesore: Top-1 accuracy - a e identifikoi agjenti shërbimin
e saktë si shkak rrënjësor? Kontrolli bëhet duke kërkuar emrin e
shërbimit ground-truth në seksionin "Shkaku rrënjësor" të diagnozës.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


def extract_root_cause_section(diagnosis: str) -> str:
    """
    Nxjerr vetëm seksionin "Shkaku rrënjësor" nga diagnoza.
    Kërkimi i emrit të shërbimit në gjithë tekstin do të jepte
    false positives, sepse shërbimet e prekura përmenden edhe te
    seksioni "Ndikimi".
    """
    if not diagnosis:
        return ""
    match = re.search(
        r"##\s*Shkaku rrënjësor\s*(.*?)(?=\n##|\Z)",
        diagnosis,
        re.DOTALL | re.IGNORECASE,
    )
    return match.group(1) if match else diagnosis[:400]


def is_correct(result: dict) -> bool:
    """A e identifikoi diagnoza shërbimin e saktë si shkak rrënjësor?"""
    ground_truth = result.get("ground_truth", "")
    section = extract_root_cause_section(result.get("diagnosis", ""))
    return ground_truth.lower() in section.lower()


def analyze(filepath: str):
    with open(filepath, encoding="utf-8") as f:
        results = json.load(f)

    results = [r for r in results if r.get("status") != "exception"]

    # Grupo sipas (skenar, konfigurim)
    groups = defaultdict(list)
    for r in results:
        groups[(r["scenario"], r["config"])].append(r)

    # Tabela për skenar dhe konfigurim
    print(f"\n{'Skenari':<32} {'Konfig':<16} {'Saktësia':<10} "
          f"{'Iter':<6} {'Sek':<7} {'Kosto'}")
    print("-" * 85)

    config_totals = defaultdict(lambda: {"correct": 0, "total": 0,
                                          "cost": 0.0, "seconds": 0.0})

    for (scenario, config), items in sorted(groups.items()):
        correct = sum(1 for i in items if is_correct(i))
        n = len(items)
        avg_iter = sum(i.get("iterations", 0) for i in items) / n
        avg_sec = sum(i.get("elapsed_seconds", 0) for i in items) / n
        avg_cost = sum(i.get("cost_usd", 0) for i in items) / n

        print(f"{scenario:<32} {config:<16} {correct}/{n} ({correct/n:.0%})  "
              f"{avg_iter:<6.1f} {avg_sec:<7.1f} ${avg_cost:.5f}")

        t = config_totals[config]
        t["correct"] += correct
        t["total"] += n
        t["cost"] += sum(i.get("cost_usd", 0) for i in items)
        t["seconds"] += sum(i.get("elapsed_seconds", 0) for i in items)

    # Përmbledhje për konfigurim
    print(f"\n{'='*85}")
    print(f"{'PËRMBLEDHJE PËR KONFIGURIM':<32}")
    print(f"{'='*85}")
    print(f"{'Konfigurimi':<20} {'Saktësia':<18} {'Koha mes.':<12} {'Kosto mes.'}")
    print("-" * 85)

    for config, t in sorted(config_totals.items()):
        acc = t["correct"] / t["total"] if t["total"] else 0
        print(f"{config:<20} {t['correct']}/{t['total']} ({acc:.1%})"
              f"{'':<6} {t['seconds']/t['total']:<12.1f} "
              f"${t['cost']/t['total']:.5f}")

    total_cost = sum(r.get("cost_usd", 0) for r in results)
    print(f"\nKosto totale e eksperimentit: ${total_cost:.4f}")

    # Listo dështimet për inspektim manual
    failures = [r for r in results if not is_correct(r)]
    if failures:
        print(f"\n{len(failures)} diagnoza të pasakta:")
        for f in failures[:10]:
            section = extract_root_cause_section(f.get("diagnosis", ""))
            preview = " ".join(section.split())[:90]
            print(f"  [{f['scenario']}/{f['config']}] pritej "
                  f"'{f['ground_truth']}' -> {preview}...")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze(sys.argv[1])
    else:
        # Merr skedarin më të fundit
        files = sorted(Path("results").glob("experiment_*.json"))
        if files:
            analyze(str(files[-1]))
        else:
            print("Asnjë skedar rezultatesh te 'results/'")