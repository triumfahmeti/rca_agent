"""
Agjenti RCA: cikli ReAct që lidh LLM-in me veglat e observabilitetit.

Cikli ndjek modelin Thought -> Action -> Observation:
1. LLM-ja arsyeton mbi informacionin që ka dhe vendos çfarë i mungon
2. Thërret një vegël për ta marrë atë informacion
3. Merr rezultatin dhe rikonsideron
4. Përsërit derisa të ketë evidencë të mjaftueshme për diagnozë
"""
import json
import time

from openai import OpenAI

from config import OPENAI_API_KEY, LLM_MODEL, MAX_ITERATIONS
from tool_schemas import TOOLS, TOOL_FUNCTIONS

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """Ti je një inxhinier i specializuar në diagnostikimin e \
incidenteve në sisteme mikroshërbimesh. Detyra jote është të gjesh shkakun \
rrënjësor të një incidenti dhe të sugjerosh veprime korrigjuese.

Sistemi nën monitorim është OpenTelemetry Demo (Astronomy Shop), një dyqan \
online me këto shërbime: frontend, frontend-proxy, checkout, cart, payment, \
product-catalog, recommendation, shipping, currency, ad, email, quote.

Zinxhiri kryesor i thirrjeve gjatë një blerjeje:
frontend -> checkout -> {cart, product-catalog, payment, shipping, currency, email}

PARIME TË RËNDËSISHME:
1. Fillo gjithmonë me pamjen e përgjithshme (get_service_health), pastaj ngushto.
2. Kur disa shërbime kanë gabime njëkohësisht, mos e supozo shkakun nga \
përqindja më e lartë. Shërbimet më lart në zinxhir (frontend) shpesh shfaqin \
gabime thjesht sepse ato poshtë dështojnë. Përdor traces për të dalluar.
3. Mos e mbyll diagnozën vetëm me metrika. Metrikat tregojnë ÇFARË, logs \
tregojnë PSE. Diagnoza pa mesazhin konkret të gabimit është e paplotë.
4. KORRELIMI ME NDRYSHIMET E KODIT. Pasi të identifikosh shërbimin e dyshuar, 
kontrollo commits e fundit PËR ATË SHËRBIM. Sugjero rikthimin (revert) e një 
commit-i VETËM nëse plotësohen të dyja kushtet: (a) commit-i prek shërbimin që 
ke identifikuar si shkak, dhe (b) është bërë pak para fillimit të incidentit. 
Nëse commit-i prek një shërbim tjetër, mos e përmend si shkak dhe mos sugjero 
rikthimin e tij. Kur kushtet plotësohen, cito hash-in dhe mesazhin.
5. Mos shpik informacion. Nëse një vegël s'kthen të dhëna, thuaje këtë \
hapur në diagnozë.
6. Kontrollo nëse incidenti është AKTIV apo ka MBARUAR. Nëse metrikat \
aktuale tregojnë gjendje normale por logs përmbajnë gabime, incidenti \
mund të ketë përfunduar. Thuaje këtë shprehimisht në diagnozë.
7. Nëse pas 2-3 veglash nuk gjen evidencë për ndonjë incident, mos vazhdo\
të kontrollosh çdo shërbim veç e veç. Përfundo me diagnozë që thotë se \
sistemi duket i shëndetshëm dhe shpjego çfarë kontrollove. Konkluzioni \
"nuk u gjet incident" është përgjigje e vlefshme.
8. Jo çdo incident prodhon gabime. Nëse get_service_health nuk tregon \
anomali të qarta, kontrollo latencën (get_service_latency) dhe burimet \
(get_container_resources) përpara se të konkludosh se s'ka incident.

Kur ke evidencë të mjaftueshme, jep diagnozën përfundimtare në këtë format:

## Shkaku rrënjësor
[Cili shërbim dhe çfarë konkretisht dështoi]

## Evidenca
[Çfarë të dhënash e mbështesin këtë përfundim]

## Ndikimi
[Cilat shërbime dhe funksionalitete preken]

## Veprime të sugjeruara
[Hapa konkretë - NUK i ekzekuton vetë, vetëm i sugjeron]

## Siguria e diagnozës
[E lartë / Mesatare / E ulët - dhe pse]
"""
# Çmimet për gpt-4o-mini (USD për 1 milion token), gusht 2026
PRICE_INPUT_PER_1M = 0.15
PRICE_OUTPUT_PER_1M = 0.60

def _execute_tool(name: str, arguments: dict) -> dict:
    """
    Ekzekuton veglën e kërkuar nga LLM-ja dhe kthen rezultatin.
    Gabimet kapen dhe kthehen si të dhëna, jo si përjashtime - kështu
    agjenti mund të vazhdojë investigimin edhe nëse një vegël dështon.
    """
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return {"status": "error", "error": f"Vegla '{name}' nuk ekziston"}

    try:
        return func(**arguments)
    except TypeError as e:
        # LLM-ja dërgoi parametra të gabuar
        return {"status": "error", "error": f"Parametra të pavlefshëm: {e}"}
    except Exception as e:
        return {"status": "error", "error": f"Vegla dështoi: {e}"}
    

def _calculate_cost(input_tokens: int, output_tokens: int) -> float:
    """Llogarit koston në USD bazuar në numrin e tokenëve."""
    cost = (
        input_tokens / 1_000_000 * PRICE_INPUT_PER_1M
        + output_tokens / 1_000_000 * PRICE_OUTPUT_PER_1M
    )
    return round(cost, 6)


def investigate(incident_description: str, verbose: bool = True,
                allowed_tools: list = None) -> dict:
    """
    Kryen një investigim të plotë RCA për incidentin e përshkruar.

    Args:
        incident_description: përshkrimi fillestar i incidentit
        verbose: nëse True, printon çdo hap gjatë ekzekutimit

    Returns:
        dict me diagnozën, numrin e iteracioneve dhe gjurmën e plotë
        të arsyetimit (për transparencë dhe auditim - FR9)
    """
        # Filtro veglat sipas konfigurimit eksperimental
    if allowed_tools is None:
        active_tools = TOOLS
    else:
        active_tools = [
            t for t in TOOLS if t["function"]["name"] in allowed_tools
        ]


    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": incident_description},
    ]

    trace = []          # gjurma e plotë e hapave, për analizë
    total_input_tokens = 0
    total_output_tokens = 0
    tool_usage = {} 
    start_time = time.time()

    for iteration in range(1, MAX_ITERATIONS + 1):
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            tools=active_tools,
            temperature=0,   # 0 për riprodhueshmëri maksimale (NFR1)
        )

        message = response.choices[0].message
        messages.append(message)

        if response.usage:
            total_input_tokens += response.usage.prompt_tokens
            total_output_tokens += response.usage.completion_tokens

        # Nëse LLM-ja nuk kërkon vegël, ka arritur në konkluzion
        if not message.tool_calls:
            elapsed = round(time.time() - start_time, 1)
            cost = _calculate_cost(total_input_tokens, total_output_tokens)
            if verbose:
                print(f"\n{'='*60}")
                print(f"DIAGNOZA (pas {iteration} iteracionesh, {elapsed}s)")
                print(f"Token: {total_input_tokens} hyrës + "
                      f"{total_output_tokens} dalës | Kosto: ${cost}")
                print(f"{'='*60}\n{message.content}")
            return {
                "status": "completed",
                "diagnosis": message.content,
                "iterations": iteration,
                "elapsed_seconds": elapsed,
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "cost_usd": _calculate_cost(total_input_tokens, total_output_tokens),
                "trace": trace,
                "tool_usage": tool_usage,
            }

        # Ekzekuto çdo vegël që kërkoi LLM-ja
        for tool_call in message.tool_calls:
            name = tool_call.function.name
            try:
                arguments = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                arguments = {}

            if verbose:
                print(f"[{iteration}] {name}({arguments})")

            # Kufizo përsëritjen e së njëjtës vegël. Pa këtë, agjenti priret
            # ta thërrasë të njëjtën vegël mbi çdo shërbim me radhë, duke
            # shteruar kufirin e iteracioneve pa konverguar.
            tool_usage[name] = tool_usage.get(name, 0) + 1
          

            if tool_usage[name] > 2:
                result = {
                    "status": "limit_reached",
                    "error": (
                        f"Vegla '{name}' është thirrur tashmë {tool_usage[name] - 1} "
                        f"herë. NDALO mbledhjen e të dhënave dhe jep diagnozën "
                        f"përfundimtare bazuar në evidencën që ke. Nëse evidenca "
                        f"nuk mjafton, thuaje këtë hapur në diagnozë."
                    ),
                }
            else:
                result = _execute_tool(name, arguments)

            if verbose:
                            print(f"      (përdorimi #{tool_usage[name]}) -> {result.get('status')}")

            trace.append({
                "iteration": iteration,
                "tool": name,
                "arguments": arguments,
                "result_status": result.get("status"),
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    # U arrit kufiri pa konkluzion
    elapsed = round(time.time() - start_time, 1)
    return {
        "status": "max_iterations_reached",
        "diagnosis": None,
        "iterations": MAX_ITERATIONS,
        "elapsed_seconds": elapsed,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cost_usd": _calculate_cost(total_input_tokens, total_output_tokens),
        "trace": trace,
        "tool_usage": tool_usage,
    }