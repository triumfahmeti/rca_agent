"""
Përshkrimet e veglave në formatin që kërkon OpenAI për tool calling.

Këto përshkrime janë i vetmi informacion që ka LLM-ja për të vendosur
cilën vegël të thërrasë. Prandaj secili përfshin jo vetëm çfarë bën
vegla, por edhe KUR duhet përdorur gjatë një investigimi.
"""
from tools.metric_tool import get_service_health, get_service_error_history
from tools.log_tool import get_service_logs
from tools.trace_tool import find_error_traces
from tools.git_tool import get_recent_commits

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_service_health",
            "description": (
                "Kthen gjendjen aktuale të TË GJITHA shërbimeve: error rate, "
                "success rate dhe përqindjen e gabimeve, të renditura nga më "
                "problematiku. Kjo është zakonisht vegla e PARË që duhet "
                "përdorur në një investigim, sepse jep pamjen e përgjithshme "
                "dhe tregon cilat shërbime kanë probleme."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "window_minutes": {
                        "type": "integer",
                        "description": "Dritarja kohore në minuta (default 5)",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_service_error_history",
            "description": (
                "Kthen historikun e gabimeve për NJË shërbim specifik, si "
                "përmbledhje trendi. Tregon nëse ka pasur ndryshim domethënës, "
                "kur filloi, dhe krahason gjendjen e mëparshme me atë aktuale. "
                "Përdore për të kuptuar KUR filloi problemi - kjo është kritike "
                "për të korreluar incidentin me ndryshime të tjera në sistem."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "Emri i shërbimit, p.sh. 'payment'",
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "Sa minuta prapa të analizohen (default 60)",
                    },
                },
                "required": ["service_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_service_logs",
            "description": (
                "Kthen mesazhet e gabimit nga logs për një shërbim, të grupuara "
                "sipas modelit (mesazhe identike numërohen së bashku). Përfshin "
                "vendndodhjen në kod ku ndodhi gabimi kur kjo është e disponueshme. "
                "Përdore për të kuptuar PSE dështoi një shërbim - metrikat tregojnë "
                "që ka gabime, por vetëm logs tregojnë mesazhin konkret."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "Emri i shërbimit",
                    },
                    "min_severity": {
                        "type": "string",
                        "description": (
                            "Niveli minimal: 'info', 'warn', 'error', 'fatal'. "
                            "Default 'warn' - disa shërbime i regjistrojnë "
                            "dështimet si warn, jo error."
                        ),
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "Sa minuta prapa (default 15)",
                    },
                },
                "required": ["service_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_error_traces",
            "description": (
                "Gjen kërkesa (traces) që dështuan dhe tregon zinxhirin e "
                "shërbimeve të përfshira, plus një vlerësim se cili shërbim "
                "është shkaku më i mundshëm rrënjësor. Përdore kur disa shërbime "
                "shfaqen me gabime njëkohësisht dhe duhet të dallosh cili është "
                "shkaku dhe cilët janë thjesht viktima të propagimit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service_name": {
                        "type": "string",
                        "description": "Emri i shërbimit nga i cili të fillojë kërkimi",
                    },
                    "lookback_minutes": {
                        "type": "integer",
                        "description": "Sa minuta prapa (default 30)",
                    },
                },
                "required": ["service_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_commits",
            "description": (
                "Kthen ndryshimet e fundit në kod (commits). Përdore për të "
                "kontrolluar nëse incidenti mund të jetë shkaktuar nga një "
                "ndryshim i fundit. Përdor parametrin 'path_filter' me dosjen "
                "e shërbimit të dyshuar (p.sh. 'src/payment') për të ngushtuar "
                "rezultatet. Mungesa e commits të fundit është gjithashtu "
                "informacion i vlefshëm - përjashton këtë hipotezë."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "since_hours": {
                        "type": "integer",
                        "description": "Sa orë prapa (default 24)",
                    },
                    "path_filter": {
                        "type": "string",
                        "description": (
                            "Filtro sipas dosjes, p.sh. 'src/payment'. "
                            "Struktura e repos: src/<emri-i-sherbimit>/"
                        ),
                    },
                },
                "required": [],
            },
        },
    },
]


TOOL_FUNCTIONS = {
    "get_service_health": get_service_health,
    "get_service_error_history": get_service_error_history,
    "get_service_logs": get_service_logs,
    "find_error_traces": find_error_traces,
    "get_recent_commits": get_recent_commits,
}