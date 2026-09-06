import requests

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
                     minutes: int = 15, limit: int = 100,
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

    return {
        "status": "ok",
        "service": service_name,
        "min_severity": min_severity,
        "window_minutes": minutes,
        "total_logs_matched": total_found,
        "logs_analyzed": len(hits),
        "unique_patterns": unique_patterns,
    }