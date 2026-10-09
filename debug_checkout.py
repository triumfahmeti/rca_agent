import json
from tools.metric_tool import _run_query

query = (
    'sum(increase(traces_span_metrics_calls_total'
    '{service_name="checkout",status_code="STATUS_CODE_ERROR"}[30m])) by (span_name)'
)
result = _run_query(query)["data"]["result"]

print("Operacionet e checkout me gabime:")
for r in sorted(result, key=lambda x: -float(x["value"][1])):
    print(f"  {r['metric'].get('span_name')}: {float(r['value'][1]):.3f} gabime")