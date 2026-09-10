import os
from dotenv import load_dotenv
load_dotenv()


PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
JAEGER_URL = os.getenv("JAEGER_URL", "http://localhost:8080/jaeger/ui")


OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://localhost:9200")


GIT_REPO_PATH = os.getenv("GIT_REPO_PATH", "./opentelemetry-demo")


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")


MAX_ITERATIONS = int(os.getenv("MAX_ITERATIONS", "8"))
