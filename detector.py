"""
Moduli i detektimit automatik të incidenteve.

Monitoron sistemin periodikisht dhe, kur zbulon anomali, nis automatikisht
agjentin RCA. Kombinon dy sinjale:
  1. Metrika: përqindja e gabimeve për shërbim (Prometheus)
  2. Logs: numri i mesazheve warn/error për shërbim (OpenSearch)

Përdorimi:
    python detector.py              # detekton dhe nis agjentin
    python detector.py --no-agent   # vetëm detekton, pa kosto API
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from tools.metric_tool import get_service_health
from tools.log_tool import get_error_log_counts

# --- Parametrat e monitorimit ---
POLL_INTERVAL = 30          # sekonda mes dy kontrolleve
WINDOW_MINUTES = 2          # dritarja kohore e secilit kontroll
WARMUP_POLLS = 6            # kontrollet e para (3 min) mësojnë gjendjen bazë
CONSECUTIVE_REQUIRED = 2    # sa kontrolle radhazi duhet të jenë anormale
COOLDOWN_SECONDS = 600      # pas një alarmi, mos e nis sërish për 10 min

# --- Pragjet ---
METRIC_ERROR_PCT = 20.0        # përqindja minimale e gabimeve
METRIC_MIN_ERROR_RATE = 0.05   # gabime/sek - filtron shërbimet me pak trafik
LOG_MIN_COUNT = 10             # numri minimal i logs warn+ në dritare
LOG_BASELINE_RATIO = 3.0       # sa herë mbi gjendjen bazë

# Shërbime që shfaqin gabime si sjellje normale ose kanë trafik minimal
IGNORED_SERVICES = {
    "load-generator", "frontend-web", "flagd", "flagd-ui", "otelcol-contrib",
}

RESULTS_DIR = Path("results")


def collect_snapshot() -> dict:
    """Mbledh gjendjen aktuale: metrika dhe numër logs për çdo shërbim."""
    health = get_service_health(window_minutes=WINDOW_MINUTES)
    logs = get_error_log_counts(minutes=WINDOW_MINUTES)

    snapshot = {}
    for s in health.get("active_services", []):
        snapshot[s["service"]] = {
            "error_pct": s["error_percentage"],
            "error_rate": s["error_rate"],
            "log_count": 0,
        }
    for service, count in logs.get("counts", {}).items():
        snapshot.setdefault(
            service, {"error_pct": 0.0, "error_rate": 0.0, "log_count": 0}
        )
        snapshot[service]["log_count"] = count

    return {k: v for k, v in snapshot.items() if k not in IGNORED_SERVICES}


def evaluate(snapshot: dict, log_baseline: dict) -> list:
    """Kthen shërbimet që tejkalojnë pragjet, bashkë me arsyen."""
    alerts = []
    for service, s in snapshot.items():
        reasons = []

        if (s["error_pct"] >= METRIC_ERROR_PCT
                and s["error_rate"] >= METRIC_MIN_ERROR_RATE):
            reasons.append(
                f"{s['error_pct']}% gabime ({s['error_rate']} gabime/sek)"
            )

        base = log_baseline.get(service, 0.0)
        threshold = max(LOG_MIN_COUNT, base * LOG_BASELINE_RATIO)
        if s["log_count"] >= threshold:
            reasons.append(
                f"{s['log_count']} logs warn/error në {WINDOW_MINUTES} min "
                f"(gjendja bazë: {base:.1f})"
            )

        if reasons:
            alerts.append({"service": service, "reasons": reasons})
    return alerts


def build_incident_description(alerts: list) -> str:
    """
    Përshkrimi i incidentit për agjentin. Përmban sinjalet e alarmit, por
    e paralajmëron shprehimisht se shërbimi i alarmit nuk është
    domosdoshmërisht shkaku - për të zbutur anësinë e ankorimit.
    """
    lines = "\n".join(
        f"- {a['service']}: {'; '.join(a['reasons'])}" for a in alerts
    )
    return (
        "Sistemi i monitorimit aktivizoi një alarm automatik. "
        f"Sinjalet që e shkaktuan:\n{lines}\n\n"
        "KUJDES: shërbimi që aktivizoi alarmin nuk është domosdoshmërisht "
        "shkaku rrënjësor - mund të jetë viktimë e propagimit nga një shërbim "
        "tjetër. Verifiko me të gjitha burimet dhe gjej shkakun rrënjësor."
    )


def run(use_agent: bool):
    RESULTS_DIR.mkdir(exist_ok=True)
    out_file = RESULTS_DIR / f"detections_{datetime.now():%Y%m%d_%H%M%S}.jsonl"

    print(f"Pragjet: metrika >= {METRIC_ERROR_PCT}% dhe >= {METRIC_MIN_ERROR_RATE} gabime/sek; "
          f"logs >= {LOG_MIN_COUNT} në {WINDOW_MINUTES} min")

    investigate, default_services = None, []
    if use_agent:
        from agent_singleshot import investigate_singleshot, DEFAULT_SERVICES
        investigate, default_services = investigate_singleshot, DEFAULT_SERVICES

    # --- Faza e ngrohjes: mëso gjendjen bazë të logs ---
    print(f"Ngrohja: {WARMUP_POLLS} kontrolle për gjendjen bazë...")
    samples = {}
    for i in range(WARMUP_POLLS):
        for service, s in collect_snapshot().items():
            samples.setdefault(service, []).append(s["log_count"])
        print(f"  {i + 1}/{WARMUP_POLLS}")
        time.sleep(POLL_INTERVAL)

    # Mesatarja mbi të gjitha kontrollet (mungesa numërohet si zero)
    log_baseline = {k: sum(v) / WARMUP_POLLS for k, v in samples.items()}
    noisy = {k: round(v, 1) for k, v in log_baseline.items() if v > 0}
    print(f"Gjendja bazë (shërbime me logs warn+): {noisy}")
    print("\nMonitorimi nisi. Ctrl+C për ta ndalur.\n")

    streak = {}
    last_trigger = 0.0

    try:
        while True:
            alerts = evaluate(collect_snapshot(), log_baseline)
            now = datetime.now().strftime("%H:%M:%S")
            alerting = {a["service"] for a in alerts}

            # Numëro kontrollet radhazi për çdo shërbim
            for service in list(streak):
                if service not in alerting:
                    streak[service] = 0
            for service in alerting:
                streak[service] = streak.get(service, 0) + 1

            confirmed = [
                a for a in alerts if streak[a["service"]] >= CONSECUTIVE_REQUIRED
            ]
            in_cooldown = time.time() - last_trigger < COOLDOWN_SECONDS

            if not alerts:
                print(f"[{now}] OK")
            elif not confirmed:
                print(f"[{now}] Sinjal i dyshimtë, pret konfirmim: {sorted(alerting)}")
            elif in_cooldown:
                print(f"[{now}] Alarm aktiv (periudhë pritjeje): {sorted(alerting)}")
            else:
                last_trigger = time.time()
                print(f"\n[{now}] ALARM: {[a['service'] for a in confirmed]}")
                for a in confirmed:
                    print(f"    {a['service']}: {'; '.join(a['reasons'])}")

                event = {"detected_at": datetime.now().isoformat(),
                         "alerts": confirmed}

                if investigate:
                    services = list(dict.fromkeys(
                        [a["service"] for a in confirmed] + default_services
                    ))
                    print("  Duke nisur agjentin RCA...")
                    result = investigate(
                        build_incident_description(confirmed),
                        verbose=False, services=services,
                    )
                    event["diagnosis"] = result.get("diagnosis")
                    event["diagnosis_seconds"] = result.get("elapsed_seconds")
                    event["cost_usd"] = result.get("cost_usd")
                    print(f"\n{result.get('diagnosis')}\n")

                with open(out_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")

            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print(f"\nMonitorimi u ndal. Ngjarjet: {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Detektimi automatik i incidenteve")
    parser.add_argument("--no-agent", action="store_true",
                        help="vetëm detekto, mos nis agjentin")
    parser.add_argument("--log-min", type=int, default=LOG_MIN_COUNT,
                        help="numri minimal i logs warn+ për alarm")
    args = parser.parse_args()
    LOG_MIN_COUNT = args.log_min
    run(use_agent=not args.no_agent)