"""
Protokoll i verbër për matjen e kohës së diagnostikimit manual (Hipoteza H1).

Skripti zgjedh rastësisht një skenar, e injekton pa e zbuluar, pret që
sinjali të shfaqet, dhe pastaj njofton inxhinierin të fillojë hetimin.
Koha matet nga njoftimi deri te përgjigjja. Në fund zbulohet skenari
i vërtetë dhe rezultati regjistrohet.
"""
import json
import random
import subprocess
import time
from datetime import datetime
from pathlib import Path

from fault_injection import SCENARIOS, _set_flag, disable_all

SIGNAL_WAIT = 90         # sekonda pas injektimit, që sinjali të shfaqet
CLEANUP_WAIT = 600       # sekonda pastrimi para provës së ardhshme
RESULTS_FILE = Path("results/manual_baseline.jsonl")


def main():
    RESULTS_FILE.parent.mkdir(exist_ok=True)
    disable_all()

    # Zgjedhje plotësisht e rastësishme. Një zgjedhje e balancuar do të lejonte
    # nxjerrjen e skenarit me eliminim (p.sh. i fundit i një raundi).
    scenario_name = random.choice(list(SCENARIOS))
    scenario = SCENARIOS[scenario_name]

    # Injektim i heshtur - thirret _set_flag direkt, sepse enable_fault()
    # printon emrin e flag-ut dhe do ta zbulonte skenarin.
    print("Po injektohet një defekt i panjohur. Mos shiko terminale të tjera.")
    _set_flag(scenario["flag"], scenario["on_variant"])
    time.sleep(SIGNAL_WAIT)

    print("\n" + "=" * 60)
    print("ALARM: Përdoruesit raportojnë probleme me dyqanin online.")
    print("Fillo hetimin TANI.")
    print("Mjetet e lejuara: Prometheus, Jaeger UI, docker logs, git log.")
    print("=" * 60)

    start = time.time()
    answer_service = input("\nShërbimi shkak: ").strip().lower()
    answer_mechanism = input("Çfarë dështoi (shkurt): ").strip()
    elapsed = round(time.time() - start, 1)

    truth = scenario["ground_truth_service"]
    correct = answer_service == truth

    print(f"\nKoha: {elapsed // 60:.0f} min {elapsed % 60:.0f} s")
    print(f"Skenari i vërtetë: {scenario_name} (shërbimi: {truth})")
    print(f"Shërbimi: {'I SAKTË' if correct else 'I GABUAR'}")

    record = {
        "timestamp": datetime.now().isoformat(),
        "scenario": scenario_name,
        "ground_truth": truth,
        "answer_service": answer_service,
        "answer_mechanism": answer_mechanism,
        "service_correct": correct,
        "elapsed_seconds": elapsed,
    }
    with open(RESULTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # Pastrimi: çaktivizim dhe rinisje e shërbimit (mësimi i degradimit të mbetur)
    disable_all()
    subprocess.run(["docker", "restart", truth], capture_output=True, timeout=60)
    print(f"\nU pastrua dhe u rinis '{truth}'. Pres {CLEANUP_WAIT // 60} min "
          f"para se të lejohet prova e ardhshme...")
    time.sleep(CLEANUP_WAIT)
    print("Gati për provën e ardhshme.")


if __name__ == "__main__":
    main()