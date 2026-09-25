"""
Kontrolli programatik i injektimit të defekteve përmes flags.

Defektet aktivizohen duke modifikuar skedarin e konfigurimit të flag-it,
i cili monitorohet automatikisht nga shërbimi dhe rilexohet kur ndryshon.
"""
import json
import time
from pathlib import Path
import subprocess

FLAGD_CONFIG = Path("opentelemetry-demo/src/flagd/demo.flagd.json")

# Skenarët eksperimentalë: emri i flag-ut, varianti për aktivizim,
# dhe shërbimi që përbën shkakun rrënjësor (ground truth).
SCENARIOS = {
    "payment_failure": {
        "flag": "paymentFailure",
        "on_variant": "100%",
        "off_variant": "off",
        "ground_truth_service": "payment",
        "description": "Shërbimi i pagesave dështon në 100% të kërkesave",
    },
    "cart_failure": {
        "flag": "cartFailure",
        "on_variant": "100%",
        "off_variant": "off",
        "ground_truth_service": "cart",
        "description": "Shërbimi i shportës dështon në 100% të kërkesave",
    },
      "ad_failure": {
        "flag": "adFailure",
        "on_variant": "on",
        "off_variant": "off",
        "ground_truth_service": "ad",
        "description": "Shërbimi i reklamave është i padisponueshëm",
    },
   
}

CONTAINER_SCENARIOS = {
    "currency_down": {
        "container": "currency",
        "ground_truth_service": "currency",
        "description": "Shërbimi i konvertimit të monedhës ndalet plotësisht",
    },
    "product_catalog_down": {
        "container": "product-catalog",
        "ground_truth_service": "product-catalog",
        "description": "Shërbimi i katalogut të produkteve ndalet plotësisht",
    },
    "recommendation_down": {
        "container": "recommendation",
        "ground_truth_service": "recommendation",
        "description": "Shërbimi i rekomandimeve ndalet plotësisht",
    },
}


def stop_container(scenario_name: str, wait_seconds: int = 45) -> dict:
    """Ndal një kontejner për të simuluar rënie shërbimi."""
    scenario = CONTAINER_SCENARIOS[scenario_name]
    subprocess.run(["docker", "stop", scenario["container"]],
                   capture_output=True, timeout=60)
    print(f"  [fault] Ndala kontejnerin '{scenario['container']}', "
          f"pres {wait_seconds}s...")
    time.sleep(wait_seconds)
    return scenario


def start_container(scenario_name: str, wait_seconds: int = 0) -> None:
    """Rinis kontejnerin dhe pret stabilizimin."""
    scenario = CONTAINER_SCENARIOS[scenario_name]
    subprocess.run(["docker", "start", scenario["container"]],
                   capture_output=True, timeout=60)
    print(f"  [fault] Rinisa kontejnerin '{scenario['container']}'")
    if wait_seconds:
        time.sleep(wait_seconds)


def _set_flag(flag_name: str, variant: str) -> None:
    """Vendos variantin e paracaktuar për një flag dhe e ruan skedarin."""
    with open(FLAGD_CONFIG, "r", encoding="utf-8") as f:
        config = json.load(f)

    if flag_name not in config["flags"]:
        raise ValueError(f"Flag '{flag_name}' nuk ekziston në konfigurim")

    config["flags"][flag_name]["defaultVariant"] = variant

    with open(FLAGD_CONFIG, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def enable_fault(scenario_name: str, wait_seconds: int = 30) -> dict:
    """
    Aktivizon defektin e një skenari dhe pret propagimin.

    Vonesa është e nevojshme sepse flagd i shpërndan ndryshimet te
    shërbimet me pak vonesë, dhe metrikat duhen mbledhur pas kësaj.
    """
    scenario = SCENARIOS[scenario_name]
    _set_flag(scenario["flag"], scenario["on_variant"])
    print(f"  [fault] Aktivizova '{scenario['flag']}' -> "
          f"{scenario['on_variant']}, pres {wait_seconds}s...")
    time.sleep(wait_seconds)
    return scenario


def disable_fault(scenario_name: str, wait_seconds: int = 0) -> None:
    """Çaktivizon defektin dhe opsionalisht pret pastrimin e dritareve."""
    scenario = SCENARIOS[scenario_name]
    _set_flag(scenario["flag"], scenario["off_variant"])
    print(f"  [fault] Çaktivizova '{scenario['flag']}'")
    if wait_seconds:
        print(f"  [fault] Pres {wait_seconds}s për pastrimin e metrikave...")
        time.sleep(wait_seconds)


def disable_all() -> None:
    """Çaktivizon të gjithë defektet - përdoret për të rivendosur gjendjen bazë."""
    for name, scenario in SCENARIOS.items():
        _set_flag(scenario["flag"], scenario["off_variant"])
    print("  [fault] Të gjithë defektet u çaktivizuan")


if __name__ == "__main__":
    # Rivendos gjendjen e pastër 
    disable_all()