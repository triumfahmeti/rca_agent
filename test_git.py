import json
from tools.git_tool import get_recent_commits

# Provo së pari pa filtër, me dritare të gjerë
# print(json.dumps(get_recent_commits(since_hours=720), indent=2, ensure_ascii=False))

# print(json.dumps(get_recent_commits(since_hours=720, path_filter="src/recommendation"), indent=2, ensure_ascii=False))

print(json.dumps(get_recent_commits(since_hours=2), indent=2, ensure_ascii=False))