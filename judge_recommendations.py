"""
Vlerëson cilësinë e veprimeve të sugjeruara në diagnozat e eksperimenteve
(metrika 'norma e rekomandimeve të zbatueshme', seksioni 4.5).

Përdor një LLM si gjyqtar me një shkallë të përcaktuar paraprakisht.
Gjyqtari e njeh ground truth-in (shërbimin dhe mekanizmin e defektit),
të cilin agjenti nuk e njihte.

Përdorimi:
    python judge_recommendations.py results/experiment_XXXX.json
"""
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from openai import OpenAI

from config import OPENAI_API_KEY

JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gpt-4o-mini")
client = OpenAI(api_key=OPENAI_API_KEY)

# Shkaku i vërtetë i secilit skenar. 'payment_unreachable' mungon qëllimisht:
# ai skenar nuk injektonte asnjë defekt, pra nuk ka veprim "të saktë".
GROUND_TRUTH = {
    "payment_failure": {
        "service": "payment",
        "mechanism": "kërkesat e pagesës dështojnë me gabimin "
                     "'Payment request failed. Invalid token.' (problem me tokenin e pagesës)",
    },
    "cart_failure": {
        "service": "cart",
        "mechanism": "shërbimi cart nuk arrin të lidhet me Redis (valkey-cart), "
                     "me gabimin 'Wasn't able to connect to redis'",
    },
    "ad_failure": {
        "service": "ad",
        "mechanism": "operacioni GetAds i shërbimit ad dështon me status UNAVAILABLE",
    },
}

JUDGE_PROMPT = """Ti vlerëson cilësinë e veprimeve korrigjuese të sugjeruara nga një \
sistem automatik diagnostikimi incidentesh. Të jepet shkaku i vërtetë i incidentit \
(i panjohur për sistemin) dhe veprimet që sugjeroi sistemi.

Shkalla e vlerësimit:
2 - Të paktën një veprim është specifik dhe adreson drejtpërdrejt mekanizmin e \
vërtetë të dështimit, te shërbimi i saktë.
1 - Të paktën një veprim specifik drejtohet te shërbimi i saktë, por asnjë nuk \
adreson mekanizmin e vërtetë.
0 - Asnjë veprim specifik nuk drejtohet te shërbimi i saktë: veprimet janë të \
përgjithshme (p.sh. vetëm "monitoro" ose "testo"), drejtohen te një shërbim i \
gabuar, ose mungojnë.

Veçmas, vendos "harmful": true nëse ndonjë veprim, po të zbatohej, do të ndryshonte \
një shërbim ose kod të palidhur me shkakun e vërtetë (p.sh. rikthimi i një commit-i \
të një shërbimi tjetër).

Kthe VETËM JSON në këtë format:
{"score": 0, "harmful": false, "reason": "një fjali shpjegimi"}"""


def extract_recommendations(diagnosis: str) -> str:
    """Nxjerr seksionin 'Veprime të sugjeruara' nga diagnoza."""
    if not diagnosis:
        return ""
    match = re.search(
        r"##\s*Veprime të sugjeruara\s*(.*?)(?=\n##|\Z)",
        diagnosis, re.DOTALL | re.IGNORECASE,
    )
    return match.group(1).strip() if match else ""


def judge(scenario: str, recommendations: str) -> dict:
    """Thërret gjyqtarin LLM për një grup veprimesh."""
    truth = GROUND_TRUTH[scenario]
    user_msg = (
        f"SHKAKU I VËRTETË:\nShërbimi: {truth['service']}\n"
        f"Mekanizmi: {truth['mechanism']}\n\n"
        f"VEPRIMET E SUGJERUARA NGA SISTEMI:\n{recommendations}"
    )
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": user_msg},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    return json.loads(response.choices[0].message.content)


def main(filepath: str):
    with open(filepath, encoding="utf-8") as f:
        results = json.load(f)

    judged = []
    for r in results:
        if r.get("status") == "exception" or r["scenario"] not in GROUND_TRUTH:
            continue

        recs = extract_recommendations(r.get("diagnosis"))
        if not recs:
            # Pa diagnozë (p.sh. max_iterations_reached) ose pa seksion veprimesh
            verdict = {"score": 0, "harmful": False, "reason": "pa veprime të sugjeruara"}
        else:
            verdict = judge(r["scenario"], recs)

        judged.append({
            "scenario": r["scenario"],
            "config": r["config"],
            "trial": r["trial"],
            "recommendations": recs,
            **verdict,
        })
        print(f"  {r['scenario']}/{r['config']}/prova {r['trial']}: "
              f"{verdict['score']}{' (I DËMSHËM)' if verdict.get('harmful') else ''}")

    out = Path(filepath).with_name(f"judged_{Path(filepath).stem}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(judged, f, ensure_ascii=False, indent=2)

    # Përmbledhje sipas konfigurimit
    groups = defaultdict(list)
    for j in judged:
        groups[j["config"]].append(j)

    print(f"\n{'Konfigurimi':<18} {'N':<4} {'Zbatueshme (>=1)':<18} "
          f"{'Mekanizmi (=2)':<16} {'Të dëmshme'}")
    print("-" * 75)
    for config, items in sorted(groups.items()):
        n = len(items)
        actionable = sum(1 for i in items if i["score"] >= 1)
        mechanism = sum(1 for i in items if i["score"] == 2)
        harmful = sum(1 for i in items if i.get("harmful"))
        print(f"{config:<18} {n:<4} {actionable}/{n} ({actionable/n:.0%}){'':<6} "
              f"{mechanism}/{n} ({mechanism/n:.0%}){'':<4} {harmful}")

    print(f"\nRezultatet u ruajtën te: {out}")


if __name__ == "__main__":
    main(sys.argv[1])