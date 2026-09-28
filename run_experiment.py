"""
Harness-i eksperimental: ekzekuton automatikisht të gjithë skenarët
mbi të gjitha konfigurimet, me numrin e caktuar të provave.

Protokolli për çdo provë:
1. Aktivizo defektin dhe prit propagimin
2. Ekzekuto secilin konfigurim
3. Çaktivizo defektin dhe prit pastrimin e dritareve
"""
import json
import time
from datetime import datetime
from pathlib import Path

from agent import investigate
from agent_singleshot import investigate_singleshot
from fault_injection import SCENARIOS, enable_fault, disable_fault, disable_all
from agent_multi import investigate_multi

# --- Parametrat e eksperimentit ---
TRIALS_PER_SCENARIO = 10
PROPAGATION_WAIT = 60      # sekonda pas aktivizimit të defektit
CLEANUP_WAIT = 330         # sekonda pas çaktivizimit (5.5 min > dritarja 5 min)

RESULTS_DIR = Path("results")

# Konfigurimet eksperimentale
CONFIGS = {
    "A_logs_only": {
        "runner": investigate,
        "kwargs": {"allowed_tools": ["get_service_logs"]},
    },
    "B_all_sources": {
        "runner": investigate,
        "kwargs": {},
    },
    "C_single_shot": {
        "runner": investigate_singleshot,
        "kwargs": {},
    },
    "D_multi_agent": {
        "runner": investigate_multi,
        "kwargs": {},
    },
}

INCIDENT_PROMPT = (
    "Përdoruesit raportojnë probleme me dyqanin online. "
    "Gjej shkakun rrënjësor."
)


def run_single_trial(scenario_name: str, config_name: str, trial: int) -> dict:
    """Ekzekuton një provë të vetme dhe kthen rezultatin me metadata."""
    config = CONFIGS[config_name]
    scenario = SCENARIOS[scenario_name]

    print(f"    -> {config_name}...", end=" ", flush=True)

    try:
        result = config["runner"](
            INCIDENT_PROMPT, verbose=False, **config["kwargs"]
        )
    except Exception as e:
        print(f"DËSHTOI: {e}")
        return {
            "scenario": scenario_name,
            "config": config_name,
            "trial": trial,
            "status": "exception",
            "error": str(e),
            "ground_truth": scenario["ground_truth_service"],
        }

    print(f"{result['status']}, {result['iterations']} iter, "
          f"${result['cost_usd']}")

    return {
        "scenario": scenario_name,
        "config": config_name,
        "trial": trial,
        "timestamp": datetime.now().isoformat(),
        "ground_truth": scenario["ground_truth_service"],
        **result,
    }


def run_experiment():
    """Ekzekuton eksperimentin e plotë."""
    RESULTS_DIR.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = RESULTS_DIR / f"experiment_{run_id}.json"

    all_results = []
    total = len(SCENARIOS) * TRIALS_PER_SCENARIO * len(CONFIGS)
    done = 0
    start = time.time()

    print(f"Eksperimenti nis: {len(SCENARIOS)} skenarë x "
          f"{TRIALS_PER_SCENARIO} prova x {len(CONFIGS)} konfigurime "
          f"= {total} ekzekutime\n")

    disable_all()
    time.sleep(10)

    for scenario_name in SCENARIOS:
        print(f"\n{'='*60}")
        print(f"SKENARI: {scenario_name} "
              f"(ground truth: {SCENARIOS[scenario_name]['ground_truth_service']})")
        print(f"{'='*60}")

        for trial in range(1, TRIALS_PER_SCENARIO + 1):
            print(f"\n  Prova {trial}/{TRIALS_PER_SCENARIO}")

            enable_fault(scenario_name, wait_seconds=PROPAGATION_WAIT)

            for config_name in CONFIGS:
                result = run_single_trial(scenario_name, config_name, trial)
                all_results.append(result)
                done += 1

                # Ruaj pas çdo prove - që të mos humbet gjithçka nëse ndërpritet
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(all_results, f, ensure_ascii=False, indent=2)

            disable_fault(scenario_name, wait_seconds=CLEANUP_WAIT)

            elapsed_min = (time.time() - start) / 60
            remaining = (elapsed_min / done) * (total - done) if done else 0
            print(f"  [{done}/{total}] Kaluar: {elapsed_min:.0f} min, "
                  f"mbetur: ~{remaining:.0f} min")

    disable_all()

    print(f"\n{'='*60}")
    print(f"PËRFUNDOI. Rezultatet: {output_file}")
    print(f"Kohëzgjatja totale: {(time.time() - start)/60:.0f} minuta")
    total_cost = sum(r.get("cost_usd", 0) for r in all_results)
    print(f"Kosto totale: ${total_cost:.4f}")


if __name__ == "__main__":
    run_experiment()