import requests
import time

from config import PROMETHEUS_URL

EXPECTED_SERVICES = {
    "frontend", "frontend-proxy", "checkout", "cart", "payment",
    "product-catalog", "recommendation", "shipping", "currency",
    "ad", "email", "quote",
}

def _run_query(promql: str) -> dict:
   
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query",
        params={"query": promql},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()

def _run_range_query(promql: str, minutes: int, step_seconds: int = 30) -> dict:

    end = time.time()
    start = end - minutes * 60

    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        params={
            "query": promql,
            "start": start,
            "end": end,
            "step": f"{step_seconds}s",
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()

def _analyze_series(values: list, threshold_ratio: float = 3.0) -> dict:

    if not values:
        return {"has_data": False}

    # Konverto në numra dhe ndaj timestamp-et nga vlerat
    points = [(float(ts), float(val)) for ts, val in values]

    first_value = points[0][1]
    last_value = points[-1][1]
    max_value = max(p[1] for p in points)
    min_value = min(p[1] for p in points)

    # Detektim i thjeshtë ndryshimi: krahaso çerekun e parë me çerekun e fundit
    quarter = max(1, len(points) // 4)
    baseline = sum(p[1] for p in points[:quarter]) / quarter
    recent = sum(p[1] for p in points[-quarter:]) / quarter

    # A ka pasur rritje domethënëse?
    change_detected = False
    change_started_seconds_ago = None

    if recent > baseline * threshold_ratio and recent > 0.001:
        change_detected = True
        # Gjej pikën e parë ku vlera kaloi mesataren mes baseline dhe recent
        midpoint = (baseline + recent) / 2
        now = time.time()
        for ts, val in points:
            if val >= midpoint:
                change_started_seconds_ago = int(now - ts)
                break
    spike_detected = max_value > baseline * threshold_ratio and max_value > 0.001
    spike_minutes_ago = None
    if spike_detected:
        now = time.time()
        for ts, val in points:
            if val == max_value:
                spike_minutes_ago = round((now - ts) / 60, 1)
                break

    return {
        "has_data": True,
        "baseline_avg": round(baseline, 4),
        "recent_avg": round(recent, 4),
        "min": round(min_value, 4),
        "max": round(max_value, 4),
        "first": round(first_value, 4),
        "last": round(last_value, 4),
        "spike_detected": spike_detected,
        "spike_minutes_ago": spike_minutes_ago,
        "change_detected": change_detected,
        "change_started_minutes_ago": (
            round(change_started_seconds_ago / 60, 1)
            if change_started_seconds_ago else None
        ),
    }

def get_service_health(window_minutes: int = 5) -> dict:
 
    promql = (
        f"sum(rate(traces_span_metrics_calls_total[{window_minutes}m]))"
        f"by(service_name,status_code)"
    )

    try:
        data = _run_query(promql)
    except requests.RequestException as e:
        return {"status": "error", "error": str(e), "services": []}

   
    by_service = {}

    for item in data["data"]["result"]:
        service = item["metric"]["service_name"]
        status = item["metric"]["status_code"]
        value = float(item["value"][1])   # vlera vjen si string, e kthejmë në numër

        if service not in by_service:
            by_service[service] = {"errors": 0.0, "success": 0.0}

        if status == "STATUS_CODE_ERROR":
            by_service[service]["errors"] += value
        else:
            by_service[service]["success"] += value

   
    active_services = []
    idle_services = []

    for service, counts in by_service.items():
        total = counts["errors"] + counts["success"]

        if total == 0:
            # Shërbim pa asnjë thirrje në këtë dritare kohore
            idle_services.append(service)
            continue

        error_pct = counts["errors"] / total * 100

        active_services.append({
            "service": service,
            "error_rate": round(counts["errors"], 4),
            "success_rate": round(counts["success"], 4),
            "error_percentage": round(error_pct, 1),
        })


    # Hapi 3: rendit shërbimet aktive sipas përqindjes së gabimeve, nga më i larti
    active_services.sort(key=lambda s: s["error_percentage"], reverse=True)

    seen = set(by_service.keys())
    missing = sorted(EXPECTED_SERVICES - seen)

    base_note = (
        "Shërbimet në 'idle_services' nuk kanë pasur asnjë thirrje në këtë "
        "dritare kohore. Kjo mund të jetë normale (p.sh. shërbime që thirren "
        "vetëm gjatë blerjes), por mund të tregojë edhe ndërprerje të plotë "
        "të shërbimit."
    )

    if missing:
        base_note += (
            f" KUJDES: shërbimet {missing} NUK shfaqen fare në metrika. "
            f"Kjo tregon se ato mund të kenë rënë plotësisht ose të jenë "
            f"të paarritshme - mungesa e telemetrisë është vetë sinjal i fortë "
            f"dhe duhet hetuar si kandidat kryesor për shkakun rrënjësor."
        )

    return {
        "status": "ok",
        "window_minutes": window_minutes,
        "active_services": active_services,
        "idle_services": sorted(idle_services),
        "missing_services": missing,
        "note": base_note,
    }

def get_service_error_history(service_name: str, minutes: int = 10) -> dict:
    """
    Kthen historikun e gabimeve për një shërbim, si përmbledhje trendi.
    Përdore për të kuptuar KUR filloi një problem dhe si u zhvillua.

    Args:
        service_name: emri i shërbimit (p.sh. "payment")
        minutes: sa minuta prapa të analizohen
    """
    promql = (
        f'sum(rate(traces_span_metrics_calls_total'
        f'{{service_name="{service_name}",status_code="STATUS_CODE_ERROR"}}[2m]))'
    )

    try:
        data = _run_range_query(promql, minutes)
    except requests.RequestException as e:
        return {"status": "error", "error": str(e)}

    result = data["data"]["result"]

    if not result:
        return {
            "status": "ok",
            "service": service_name,
            "has_data": False,
            "note": f"Asnjë gabim i regjistruar për '{service_name}' në {minutes} minutat e fundit.",
        }

    analysis = _analyze_series(result[0]["values"])

    return {
        "status": "ok",
        "service": service_name,
        "window_minutes": minutes,
        "metric": "error_rate",
        **analysis,
    }


def get_service_latency(window_minutes: int = 5) -> dict:
    """
    Kthen latencën (p50, p95, p99) për të gjitha shërbimet, të renditura
    nga më i ngadalti. Përdore kur dyshohet degradim performance dhe jo
    dështim - shërbimet mund të jenë "të shëndetshme" nga pikëpamja e
    gabimeve, por shumë të ngadalta.
    """
    quantiles = {"p50": 0.5, "p95": 0.95, "p99": 0.99}
    by_service = {}

    for label, q in quantiles.items():
        promql = (
            f"histogram_quantile({q}, sum(rate("
            f"traces_span_metrics_duration_milliseconds_bucket"
            f"[{window_minutes}m])) by (le, service_name))"
        )
        try:
            data = _run_query(promql)
        except requests.RequestException as e:
            return {"status": "error", "error": str(e), "services": []}

        for item in data["data"]["result"]:
            service = item["metric"].get("service_name")
            if not service:
                continue
            raw = item["value"][1]
            # Prometheus kthen "NaN" si string për shërbime pa të dhëna
            if raw == "NaN":
                continue
            by_service.setdefault(service, {})[label] = round(float(raw), 1)

    services = [
        {"service": s, **vals}
        for s, vals in by_service.items()
        if vals.get("p95") is not None
    ]
    services.sort(key=lambda s: s.get("p95", 0), reverse=True)

    return {
        "status": "ok",
        "window_minutes": window_minutes,
        "unit": "millisekonda",
        "services": services,
        "note": (
            "Latenca e lartë pa gabime tregon degradim performance, jo dështim. "
            "Shërbimet 'load-generator', 'flagd-ui' dhe 'flagd' mund të kenë "
            "vlera shumë të larta për shkak të lidhjeve afatgjata - kjo është "
            "normale dhe nuk tregon problem."
        ),
    }


def get_container_resources() -> dict:
    """
    Kthen shfrytëzimin e CPU dhe memories për çdo kontejner, të renditur
    sipas CPU-së. Përdore kur dyshohet problem burimesh - p.sh. një shërbim
    që konsumon CPU jashtëzakonisht shumë ose i afrohet limitit të memories.
    """
    resources = {}

    try:
        cpu_data = _run_query("container_cpu_utilization_ratio")
        mem_data = _run_query("container_memory_percent_ratio")
    except requests.RequestException as e:
        return {"status": "error", "error": str(e), "containers": []}

    for item in cpu_data["data"]["result"]:
        name = item["metric"].get("container_name")
        if name:
            resources.setdefault(name, {})["cpu_percent"] = round(
                float(item["value"][1]), 1
            )

    for item in mem_data["data"]["result"]:
        name = item["metric"].get("container_name")
        if name:
            resources.setdefault(name, {})["memory_percent"] = round(
                float(item["value"][1]), 1
            )

    containers = [{"container": n, **v} for n, v in resources.items()]
    containers.sort(key=lambda c: c.get("cpu_percent", 0), reverse=True)

    return {
        "status": "ok",
        "containers": containers,
        "note": (
            "CPU mbi ~50% për një shërbim aplikacioni është e pazakontë dhe "
            "mund të tregojë ngarkesë anormale. Kontejneri 'load-generator' "
            "pritet të ketë CPU të lartë - kjo është funksioni i tij."
        ),
    }

# if __name__ == "__main__":
#     import json
#     print(json.dumps(get_service_health(), indent=2, ensure_ascii=False))