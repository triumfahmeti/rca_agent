"""
Konfigurimi D: arkitekturë multi-agent me specialistë dhe koordinues.

Tre agjentë specialistë, secili me akses vetëm te veglat e domenit të vet,
ekzekutohen në rend fiks: metrika -> logs -> traces. Secili kthen një
strukturë JSON të fiksuar. Një agjent koordinues, pa akses te veglat,
sintetizon rezultatet e tyre në diagnozën përfundimtare.

Rendi fiks dhe struktura e fiksuar zgjidhen qëllimisht për të zvogëluar
ndryshueshmërinë mes ekzekutimeve dhe për të shmangur eksplorimin e
pakontrolluar të vëzhguar te konfigurimi B.
"""
import json
import time

from openai import OpenAI

from config import OPENAI_API_KEY, LLM_MODEL, MAX_ITERATIONS
from agent import _calculate_cost, _execute_tool
from tool_schemas import TOOLS

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_CONTEXT = """Sistemi nën monitorim është OpenTelemetry Demo (Astronomy \
Shop), një dyqan online me këto shërbime: frontend, frontend-proxy, checkout, \
cart, payment, product-catalog, recommendation, shipping, currency, ad, email, quote.

Zinxhiri kryesor i thirrjeve gjatë një blerjeje:
frontend -> checkout -> {cart, product-catalog, payment, shipping, currency, email}
"""

# --- Specialistët: emri, veglat e lejuara, detyra dhe formati i përgjigjes ---

SPECIALISTS = {
    "metrics": {
        "tools": [
            "get_service_health",
            "get_service_error_history",
            "get_service_latency",
            "get_container_resources",
        ],
        "prompt": SYSTEM_CONTEXT + """
Ti je specialist i METRIKAVE. Detyra jote e vetme është të identifikosh cilat \
shërbime shfaqin sjellje anormale, duke u bazuar VETËM te metrikat.

Mos u përpjek të japësh diagnozë përfundimtare - kjo është detyrë e koordinuesit. \
Ti thjesht identifikon kandidatët e dyshimtë dhe i rendit sipas nivelit të dyshimit.

KUJDES: shërbimet 'frontend', 'frontend-proxy' dhe 'load-generator' shfaqin gabime \
sa herë që ndonjë shërbim poshtë tyre dështon. Mos i rendit si kandidatë kryesorë \
përveç nëse janë të vetmit me anomali.

Kthe VETËM një objekt JSON, pa tekst tjetër, në këtë format:
{
  "candidates": ["emri_sherbimit_1", "emri_sherbimit_2"],
  "evidence": "përshkrim i shkurtër i asaj që gjete",
  "anomaly_detected": true/false
}""",
    },
    "logs": {
        "tools": ["get_service_logs"],
        "prompt": SYSTEM_CONTEXT + """
Ti je specialist i LOGS. Detyra jote e vetme është të gjesh mesazhet konkrete të \
gabimit për shërbimet që të jepen.

Kontrollo secilin shërbim të listuar. Nëse një shërbim nuk ka logs, thuaje këtë \
hapur - mos shpik. Nëse gjen mesazh gabimi, cito atë fjalë për fjalë.

Kthe VETËM një objekt JSON, pa tekst tjetër, në këtë format:
{
  "findings": [
    {"service": "emri", "error_message": "mesazhi ose null", "count": numri, "code_location": "vendi ose null"}
  ],
  "most_significant": "emri i shërbimit me gabimin më domethënës ose null"
}""",
    },
    "traces": {
        "tools": ["find_error_traces"],
        "prompt": SYSTEM_CONTEXT + """
Ti je specialist i TRACES. Detyra jote e vetme është të përcaktosh zinxhirin e \
thirrjeve dhe të dallosh shkakun nga pasoja.

Në një zinxhir thirrjesh, shërbimi që dështon i pari është shkaku; ato mbi të në \
zinxhir dështojnë si pasojë. Vegla kthen një fushë 'likely_root_cause_service' - \
merre parasysh, por verifikoje me zinxhirin e plotë.

Kthe VETËM një objekt JSON, pa tekst tjetër, në këtë format:
{
  "root_cause_candidate": "emri i shërbimit ose null",
  "affected_chain": ["sherbimi_1", "sherbimi_2"],
  "evidence": "përshkrim i shkurtër"
}""",
    },
}

COORDINATOR_PROMPT = SYSTEM_CONTEXT + """
Ti je koordinuesi i një ekipi diagnostik. Tre specialistë kanë analizuar incidentin, \
secili nga këndvështrimi i vet. Detyra jote është të sintetizosh gjetjet e tyre në \
një diagnozë përfundimtare.

PARIME:
1. Kur specialistët bien ndesh, jepi përparësi evidencës konkrete (mesazh gabimi nga \
logs, zinxhir nga traces) mbi sinjaleve statistikore (përqindje gabimesh).
2. Një shërbim mund të jetë shkaku edhe nëse metrikat nuk tregojnë anomali te ai - \
disa dështime nuk regjistrohen si gabime në metrika.
3. Mos shpik informacion. Nëse specialistët nuk kanë gjetur evidencë të mjaftueshme, \
thuaje këtë hapur.
4. Shërbimet 'frontend', 'frontend-proxy' dhe 'load-generator' janë rrallë shkaku - \
ato shfaqin gabime si pasojë e dështimeve më poshtë në zinxhir.
5. Nëse ka një commit të fundit te shërbimi i dyshuar, përmende shprehimisht 
te "Shkaku rrënjësor" me hash dhe mesazh, dhe sugjero rikthimin e tij si 
veprim të parë.

Jep diagnozën në këtë format:

## Shkaku rrënjësor
[Cili shërbim dhe çfarë konkretisht dështoi]

## Evidenca
[Çfarë të dhënash e mbështesin, duke përmendur cili specialist e gjeti]

## Ndikimi
[Cilat shërbime dhe funksionalitete preken]

## Veprime të sugjeruara
[Hapa konkretë - NUK i ekzekuton vetë, vetëm i sugjeron]

## Siguria e diagnozës
[E lartë / Mesatare / E ulët - dhe pse]
"""


def _run_specialist(name: str, task: str, verbose: bool) -> tuple:
    """
    Ekzekuton një agjent specialist me cikël ReAct të kufizuar.
    Kthen (rezultati_i_parsuar, input_tokens, output_tokens).
    """
    spec = SPECIALISTS[name]
    active_tools = [t for t in TOOLS if t["function"]["name"] in spec["tools"]]

    messages = [
        {"role": "system", "content": spec["prompt"]},
        {"role": "user", "content": task},
    ]

    input_tokens = 0
    output_tokens = 0
    tool_usage = {}

    for _ in range(MAX_ITERATIONS):
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            tools=active_tools,
            temperature=0,
        )
        message = response.choices[0].message
        messages.append(message)

        if response.usage:
            input_tokens += response.usage.prompt_tokens
            output_tokens += response.usage.completion_tokens

        if not message.tool_calls:
            # Specialisti përfundoi - parso përgjigjen JSON
            content = message.content or "{}"
            cleaned = content.replace("```json", "").replace("```", "").strip()
            try:
                return json.loads(cleaned), input_tokens, output_tokens
            except json.JSONDecodeError:
                # Nëse s'është JSON i vlefshëm, ktheje si tekst
                return {"raw_response": content}, input_tokens, output_tokens

        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            if verbose:
                print(f"    [{name}] {tool_name}({arguments})")

            tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1
            if tool_usage[tool_name] > 3:
                result = {
                    "status": "limit_reached",
                    "error": "Vegla është thirrur mjaftueshëm. Jep përgjigjen JSON tani.",
                }
            else:
                result = _execute_tool(tool_name, arguments)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    return {"error": "specialisti nuk konvergoi"}, input_tokens, output_tokens


def investigate_multi(incident_description: str, verbose: bool = True) -> dict:
    """
    Kryen investigimin me arkitekturë multi-agent.
    Specialistët ekzekutohen në rend fiks: metrika -> logs -> traces.
    """
    start_time = time.time()
    total_in = 0
    total_out = 0
    trace = []

    # --- Hapi 1: specialisti i metrikave ---
    if verbose:
        print("  [1/4] Specialisti i metrikave...")
    metrics_result, ti, to = _run_specialist(
        "metrics",
        f"Incidenti: {incident_description}\n\n"
        f"Identifiko shërbimet me sjellje anormale.",
        verbose,
    )
    total_in += ti
    total_out += to
    trace.append({"specialist": "metrics", "result": metrics_result})

    candidates = metrics_result.get("candidates", [])

    # Shto gjithmonë shërbimet kryesore të zinxhirit të blerjes. Kjo është
    # e domosdoshme sepse disa dështime (p.sh. cart) nuk regjistrohen fare
    # në metrika, dhe specialisti i metrikave nuk mund të propozojë si
    # kandidat një shërbim që nuk e sheh. Pa këtë, gabimi i hapit të parë
    # trashëgohet nga të gjithë hapat pasues.
    CORE_SERVICES = ["payment", "cart", "checkout", "product-catalog", "ad"]
    candidates = list(dict.fromkeys(candidates + CORE_SERVICES))[:6]

    # --- Hapi 2: specialisti i logs ---
    if verbose:
        print(f"  [2/4] Specialisti i logs (kandidatët: {candidates})...")
    logs_result, ti, to = _run_specialist(
        "logs",
        f"Incidenti: {incident_description}\n\n"
        f"Kontrollo logs për këto shërbime: {', '.join(candidates)}",
        verbose,
    )
    total_in += ti
    total_out += to
    trace.append({"specialist": "logs", "result": logs_result})

    # --- Hapi 3: specialisti i traces ---
    if verbose:
        print("  [3/4] Specialisti i traces...")
    traces_result, ti, to = _run_specialist(
        "traces",
        f"Incidenti: {incident_description}\n\n"
        f"Përcakto zinxhirin e dështimit. Shërbimet e dyshuara: "
        f"{', '.join(candidates)}",
        verbose,
    )
    total_in += ti
    total_out += to
    trace.append({"specialist": "traces", "result": traces_result})

     # --- Hapi 3b: kontrolli i ndryshimeve të kodit (deterministik) ---
    # Kryhet në kod, jo nga një agjent, në përputhje me qasjen e rendit fiks.
    # Kontrollohen commits për shërbimin më të dyshuar sipas logs.
    from tools.git_tool import get_recent_commits

    suspect = logs_result.get("most_significant") or (candidates[0] if candidates else None)
    commits_result = (
        get_recent_commits(since_hours=24, path_filter=f"src/{suspect}")
        if suspect else {"note": "asnjë shërbim i dyshuar"}
    )
    trace.append({"specialist": "git", "result": commits_result})

    # --- Hapi 4: koordinuesi ---
    if verbose:
        print("  [4/4] Koordinuesi sintetizon...")

    synthesis_input = f"""INCIDENTI:
{incident_description}
NDRYSHIMET E FUNDIT NË KOD PËR SHËRBIMIN E DYSHUAR ({suspect}):
{json.dumps(commits_result, ensure_ascii=False, indent=2)}

GJETJET E SPECIALISTIT TË METRIKAVE:
{json.dumps(metrics_result, ensure_ascii=False, indent=2)}

GJETJET E SPECIALISTIT TË LOGS:
{json.dumps(logs_result, ensure_ascii=False, indent=2)}

GJETJET E SPECIALISTIT TË TRACES:
{json.dumps(traces_result, ensure_ascii=False, indent=2)}

Sintetizo diagnozën përfundimtare."""

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": COORDINATOR_PROMPT},
            {"role": "user", "content": synthesis_input},
        ],
        temperature=0,
    )

    diagnosis = response.choices[0].message.content
    if response.usage:
        total_in += response.usage.prompt_tokens
        total_out += response.usage.completion_tokens

    elapsed = round(time.time() - start_time, 1)
    cost = _calculate_cost(total_in, total_out)

    if verbose:
        print(f"\n{'='*60}")
        print(f"DIAGNOZA MULTI-AGENT ({elapsed}s)")
        print(f"Token: {total_in} hyrës + {total_out} dalës | Kosto: ${cost}")
        print(f"{'='*60}\n{diagnosis}")

    return {
        "status": "completed",
        "diagnosis": diagnosis,
        "iterations": 4,          # tre specialistë + koordinuesi
        "elapsed_seconds": elapsed,
        "input_tokens": total_in,
        "output_tokens": total_out,
        "cost_usd": cost,
        "trace": trace,
        "tool_usage": {"multi_agent": 4},
    }


if __name__ == "__main__":
    investigate_multi(
        "Përdoruesit raportojnë probleme me dyqanin online. Gjej shkakun rrënjësor."
    )