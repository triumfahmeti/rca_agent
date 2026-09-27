"""
Konfigurimi C: agjent single-shot pa orkestrim iterativ.

Të gjitha veglat ekzekutohen paraprakisht me parametra fikse, rezultatet
futen në një prompt të vetëm, dhe LLM-ja prodhon diagnozën në një hap.

Krahasimi me Konfigurimin B izolon variablin "orkestrim iterativ": të dy
kanë qasje te të njëjtat burime, por B vendos vetë çfarë të pyesë dhe kur,
ndërsa C merr një grumbull të dhënash të paracaktuar. Kjo teston Hipotezën H2.
"""
import json
import time

from openai import OpenAI

from config import OPENAI_API_KEY, LLM_MODEL
from agent import SYSTEM_PROMPT, _calculate_cost
from tools.metric_tool import (
    get_service_health,
    get_service_error_history,
    get_service_latency,
    get_container_resources,
)
from tools.log_tool import get_service_logs
from tools.trace_tool import find_error_traces
from tools.git_tool import get_recent_commits

client = OpenAI(api_key=OPENAI_API_KEY)

# Shërbimet për të cilat mblidhen të dhëna paraprakisht. Meqë agjenti
# single-shot nuk mund të vendosë vetë ku të shikojë, ne i japim të dhëna
# për shërbimet kryesore të zinxhirit të blerjes.
DEFAULT_SERVICES = ["payment", "checkout", "cart", "recommendation", "product-catalog", "frontend"]


def collect_all_data(services: list = None) -> dict:
    """
    Ekzekuton të gjitha veglat me parametra fikse dhe mbledh rezultatet.
    """
    services = services or DEFAULT_SERVICES

    data = {
        "service_health": get_service_health(),
        "service_latency": get_service_latency(),
        "container_resources": get_container_resources(),
        "per_service": {},
        "recent_commits": get_recent_commits(since_hours=24),
    }

    for service in services:
        data["per_service"][service] = {
            "error_history": get_service_error_history(service, minutes=10),
            "logs": get_service_logs(service, min_severity="warn", minutes=5),
            "error_traces": find_error_traces(service, lookback_minutes=10),
        }

    return data


def investigate_singleshot(incident_description: str, verbose: bool = True) -> dict:
    """
    Prodhon një diagnozë me një thirrje të vetme LLM, mbi të dhëna të
    mbledhura paraprakisht.
    """
    start_time = time.time()

    if verbose:
        print("Duke mbledhur të dhëna nga të gjitha burimet...")

    data = collect_all_data()

    prompt = f"""INCIDENTI:
{incident_description}

TË DHËNAT E MBLEDHURA NGA SISTEMI I MONITORIMIT:
{json.dumps(data, ensure_ascii=False, indent=2)}

Bazuar VETËM në të dhënat e mësipërme, jep diagnozën përfundimtare.
"""

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
    )

    diagnosis = response.choices[0].message.content
    elapsed = round(time.time() - start_time, 1)

    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0
    cost = _calculate_cost(input_tokens, output_tokens)

    if verbose:
        print(f"\n{'='*60}")
        print(f"DIAGNOZA SINGLE-SHOT ({elapsed}s)")
        print(f"Token: {input_tokens} hyrës + {output_tokens} dalës | Kosto: ${cost}")
        print(f"{'='*60}\n{diagnosis}")

    return {
        "status": "completed",
        "diagnosis": diagnosis,
        "iterations": 1,
        "elapsed_seconds": elapsed,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost,
        "trace": [{"note": "single-shot: të gjitha veglat u ekzekutuan paraprakisht"}],
        "tool_usage": {"all_tools_preloaded": 1},
    }


if __name__ == "__main__":
    investigate_singleshot(
        "Përdoruesit raportojnë se nuk mund të përfundojnë blerjen në dyqan. "
        "Gjej shkakun rrënjësor."
    )