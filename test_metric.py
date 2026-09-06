import json
from tools.metric_tool import get_service_health
from tools.metric_tool import get_service_error_history
from tools.log_tool import get_service_logs

# print(json.dumps(get_service_health(), indent=2, ensure_ascii=False))

# print(json.dumps(get_service_error_history("payment", minutes=60), indent=2, ensure_ascii=False))

print(json.dumps(get_service_logs("payment", minutes=1440), indent=2, ensure_ascii=False))