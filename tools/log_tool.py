import requests

from datetime import datetime, timezone
from config import OPENSEARCH_URL

SEVERITY_LEVELS = {
    "trace": 1,
    "debug": 5,
    "info": 9,
    "warn": 13,
    "error": 17,
    "fatal": 21,
}

def get_service_logs(service_name: str, min_severity: str = "warn",
                     minutes: int = 5, limit: int = 100,
                     search_text: str = None) -> dict:
   
    min_number = SEVERITY_LEVELS.get(min_severity.lower(), 13)

    must_clauses = [
        {"term": {"resource.service.name.keyword": service_name}},
        {"range": {"severity.number": {"gte": min_number}}},
        {"range": {"@timestamp": {"gte": f"now-{minutes}m"}}},
    ]

    if search_text:
        must_clauses.append({"match_phrase": {"body": search_text}})

    query = {
        "query": {"bool": {"must": must_clauses}},
        "sort": [{"@timestamp": {"order": "desc"}}],
        "size": limit,
    }

    try:
        response = requests.post(
            f"{OPENSEARCH_URL}/otel-logs-*/_search",
            json=query,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        return {"status": "error", "error": str(e), "logs": []}

    hits = data.get("hits", {}).get("hits", [])


    patterns = {}

    for hit in hits:
        source = hit["_source"]
        attributes = source.get("attributes", {})
        message = source.get("body", "")
        stacktrace = attributes.get("exception.stacktrace", "")


        if stacktrace:
            stack_lines = stacktrace.split("\n")
            signature = stack_lines[1].strip() if len(stack_lines) > 1 else message
        else:
            signature = message

        timestamp = source.get("@timestamp")

        if signature not in patterns:
            patterns[signature] = {
                "message": message,
                "severity": source.get("severity", {}).get("text"),
                "count": 0,
                "first_seen": timestamp,
                "last_seen": timestamp,
                "sample_trace_id": source.get("traceId"),
            }
            
            if stacktrace:
                patterns[signature]["code_location"] = signature

        entry = patterns[signature]
        entry["count"] += 1

        # Përditëso intervalin kohor (logs vijnë nga i riu te i vjetri)
        if timestamp < entry["first_seen"]:
            entry["first_seen"] = timestamp
        if timestamp > entry["last_seen"]:
            entry["last_seen"] = timestamp

    # Rendit sipas frekuencës - problemi më i shpeshtë i pari
    unique_patterns = sorted(
        patterns.values(), key=lambda p: p["count"], reverse=True
    )

    total = data.get("hits", {}).get("total", {})
    total_found = total.get("value", 0) if isinstance(total, dict) else total

    if not unique_patterns:
        note = (
            f"Nuk u gjet asnjë log me nivel '{min_severity}' ose më lart për "
            f"shërbimin '{service_name}' në {minutes} minutat e fundit. "
            f"KJO NUK do të thotë që shërbimi s'ka probleme, dhe NUK tregon "
            f"ndonjë problem me sistemin e logs. Provo përsëri me "
            f"min_severity='warn' ose 'info', ose me një dritare më të gjatë."
        )
    else:
        # Llogarit sa kohë ka kaluar nga gabimi i fundit. Nëse ka kaluar
        # një pjesë e konsiderueshme e dritares pa gabime të reja, incidenti
        # mund të ketë përfunduar - kjo është informacion kritik që LLM-ja
        # nuk duhet ta llogarisë vetë.
        latest_iso = max(p["last_seen"] for p in unique_patterns)
        staleness_note = ""

        try:
            # Timestamp-et vijnë në format ISO me 'Z' në fund
            latest_dt = datetime.fromisoformat(latest_iso.replace("Z", "+00:00"))
            minutes_since_last = (
                datetime.now(timezone.utc) - latest_dt
            ).total_seconds() / 60

            if minutes_since_last > minutes * 0.4:
                staleness_note = (
                    f" KUJDES: gabimi i fundit ndodhi rreth "
                    f"{round(minutes_since_last)} minuta më parë. Nuk ka gabime "
                    f"të reja që atëherë, çka sugjeron se incidenti mund të ketë "
                    f"PËRFUNDUAR. Verifiko me metrikat aktuale para se ta "
                    f"raportosh si aktiv."
                )
            else:
                staleness_note = (
                    f" Gabimi i fundit ndodhi rreth "
                    f"{round(minutes_since_last)} minuta më parë - incidenti "
                    f"duket AKTIV."
                )
        except (ValueError, AttributeError):
            pass

        note = (
            f"U gjetën {len(unique_patterns)} model(e) unike gabimi. "
            f"Fusha 'code_location' tregon vendin në kod ku ndodhi gabimi."
            + staleness_note
        )

    return {
        "status": "ok",
        "service": service_name,
        "min_severity": min_severity,
        "window_minutes": minutes,
        "total_logs_matched": total_found,
        "logs_analyzed": len(hits),
        "unique_patterns": unique_patterns,
        "note": note,
    }

def get_error_log_counts(minutes: int = 2) -> dict:
    """
    Kthen numrin e logs me nivel warn ose më lart për ÇDO shërbim, me një
    thirrje të vetme. Përdoret nga moduli i detektimit, që duhet t'i
    kontrollojë të gjitha shërbimet shpejt dhe shpesh.

    E nevojshme sepse disa incidente (p.sh. cart_failure) nuk shfaqen fare
    në metrika dhe janë të dukshme vetëm në logs.
    """
    query = {
        "size": 0,
        "query": {
            "bool": {
                "must": [
                    {"range": {"severity.number": {"gte": SEVERITY_LEVELS["warn"]}}},
                    {"range": {"@timestamp": {"gte": f"now-{minutes}m"}}},
                ]
            }
        },
        "aggs": {
            "by_service": {
                "terms": {"field": "resource.service.name.keyword", "size": 50}
            }
        },
    }

    try:
        response = requests.post(
            f"{OPENSEARCH_URL}/otel-logs-*/_search", json=query, timeout=15
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        return {"status": "error", "error": str(e), "counts": {}}

    buckets = data.get("aggregations", {}).get("by_service", {}).get("buckets", [])
    counts = {b["key"]: b["doc_count"] for b in buckets}
    return {"status": "ok", "window_minutes": minutes, "counts": counts}