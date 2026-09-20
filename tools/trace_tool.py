
import requests

from config import JAEGER_URL


def _get_tag(span: dict, key: str):
    for tag in span.get("tags", []):
        if tag.get("key") == key:
            return tag.get("value")
    return None


def _has_error(span: dict) -> bool:

    if _get_tag(span, "error") is True:
        return True

    if _get_tag(span, "otel.status_code") == "ERROR":
        return True

    for key in ("http.status_code", "http.response.status_code"):
        code = _get_tag(span, key)
        if code and str(code).startswith(("4", "5")):
            return True

    for key in ("rpc.grpc.status_code", "grpc.status_code"):
        code = _get_tag(span, key)
        if code is not None and str(code) != "0":
            return True

    for key in ("rpc.response.status_code",):
        code = _get_tag(span, key)
        if code and str(code).upper() not in ("OK", "0"):
            return True

    return False


def find_error_traces(service_name: str, limit: int = 5,
                       lookback_minutes: int = 10) -> dict:
  
    params = {
        "service": service_name,
        "limit": limit,
        "lookback": f"{lookback_minutes}m",
        # "tags": '{"error":"true"}',
    }

    try:
        response = requests.get(f"{JAEGER_URL}/api/traces", params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        return {"status": "error", "error": str(e), "traces": []}

    traces = []
    for trace in data.get("data", []):
        spans = trace.get("spans", [])
        processes = trace.get("processes", {})

        error_spans = [s for s in spans if _has_error(s)]

        # Kalo traces që s'kanë asnjë gabim
        if not error_spans:
            continue

        # Gjej shërbimet e përfshira në gabime
        failing_services = set()
        for span in error_spans:
            pid = span.get("processID")
            service = processes.get(pid, {}).get("serviceName", "unknown")
            failing_services.add(service)

        # Gjej root span-in: atë që s'ka referencë prindi brenda këtij trace-i.
        # Kohëzgjatja e tij përfaqëson kërkesën reale, ndryshe nga min/max mbi
        # të gjitha spans-et, që shtrembërohet nga lidhje afatgjata (streaming).
        root_span = None
        for span in spans:
            if not span.get("references"):
                root_span = span
                break

        root_duration_ms = round(root_span["duration"] / 1000, 1) if root_span else None

        # Shërbimi me span-in e gabimit më të thellë është kandidati kryesor
        # për shkakun rrënjësor - gabimet mbi të janë propagim.
        deepest_error_service = None
        if error_spans:
            deepest = min(error_spans, key=lambda s: s["duration"])
            pid = deepest.get("processID")
            deepest_error_service = processes.get(pid, {}).get("serviceName")

        traces.append({
            "trace_id": trace.get("traceID"),
            "root_duration_ms": root_duration_ms,
            "total_spans": len(spans),
            "error_spans": len(error_spans),
            "failing_services": sorted(failing_services),
            "likely_root_cause_service": deepest_error_service,
        })

    return {
        "status": "ok",
        "service": service_name,
        "found": len(traces),
        "traces": traces,
    }