import json
from tools.trace_tools import find_error_traces

print(json.dumps(find_error_traces("payment", lookback_minutes=1440), indent=2, ensure_ascii=False))