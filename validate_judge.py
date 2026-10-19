"""
Validim manual i gjyqtarit LLM mbi një mostër të rastësishme.

Hetuesi vlerëson pa e parë pikën e gjyqtarit (vlerësim i verbër);
në fund llogaritet përputhja mes tyre.

Përdorimi:
    python validate_judge.py results/judged_experiment_XXXX.json
"""
import json
import random
import sys
from collections import Counter

from judge_recommendations import GROUND_TRUTH

SAMPLE_SIZE = 20
SEED = 7   # i fiksuar, që mostra të jetë e riprodhueshme


def cohen_kappa(a: list, b: list) -> float:
    """Kappa e Cohen-it: përputhja e korrigjuar për rastësinë."""
    n = len(a)
    observed = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return (observed - expected) / (1 - expected) if expected < 1 else 1.0


def main(filepath: str):
    with open(filepath, encoding="utf-8") as f:
        judged = json.load(f)

    # Përjashto rastet pa veprime - vlerësimi i tyre është i parëndësishëm
    eligible = [j for j in judged if j["recommendations"]]
    sample = random.Random(SEED).sample(eligible, min(SAMPLE_SIZE, len(eligible)))

    print("SHKALLA E VLERËSIMIT (e njëjtë me atë të gjyqtarit):")
    print("  2 - Të paktën një veprim specifik që adreson mekanizmin e vërtetë,")
    print("      te shërbimi i saktë")
    print("  1 - Veprim specifik te shërbimi i saktë, por pa adresuar mekanizmin")
    print("  0 - Asnjë veprim specifik te shërbimi i saktë (vetëm 'monitoro',")
    print("      shërbim i gabuar, ose mungojnë)")
    print("\nI DËMSHËM = ndonjë veprim që do të ndryshonte diçka të palidhur me")
    print("shkakun (p.sh. revert i commit-it të një shërbimi tjetër).")
    print("Pika 0 NUK do të thotë i dëmshëm.\n")
    print("Pika e gjyqtarit NUK shfaqet deri në fund.\n")

    manual = []
    for i, item in enumerate(sample, 1):
        truth = GROUND_TRUTH[item["scenario"]]
        print("=" * 70)
        print(f"[{i}/{len(sample)}] Shkaku i vërtetë: {truth['service']} — {truth['mechanism']}")
        print("-" * 70)
        print(item["recommendations"])
        print("-" * 70)

        while True:
            score = input("Pika (0/1/2): ").strip()
            if score in ("0", "1", "2"):
                break
        harmful = input("Ndonjë veprim i dëmshëm? (p=po / j=jo): ").strip().lower() == "p"
        manual.append({**item, "manual_score": int(score), "manual_harmful": harmful})

    judge_scores = [m["score"] for m in manual]
    manual_scores = [m["manual_score"] for m in manual]

    exact = sum(1 for a, b in zip(judge_scores, manual_scores) if a == b)
    act_agree = sum(1 for a, b in zip(judge_scores, manual_scores)
                    if (a >= 1) == (b >= 1))
    n = len(manual)

    print("\n" + "=" * 70)
    print(f"Përputhje e saktë (0/1/2):        {exact}/{n} ({exact/n:.0%})")
    print(f"Përputhje për 'i zbatueshëm':     {act_agree}/{n} ({act_agree/n:.0%})")
    print(f"Kappa e Cohen-it:                 {cohen_kappa(judge_scores, manual_scores):.2f}")

    disagreements = [m for m in manual if m["score"] != m["manual_score"]]
    if disagreements:
        print(f"\nMospërputhjet ({len(disagreements)}):")
        for m in disagreements:
            print(f"  {m['scenario']}/{m['config']}/prova {m['trial']}: "
                  f"gjyqtari {m['score']}, ti {m['manual_score']}")

    with open("results/manual_validation_2.json", "w", encoding="utf-8") as f:
        json.dump(manual, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main(sys.argv[1])
    