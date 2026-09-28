"""
Krahasim i konfigurimeve eksperimentale A dhe B.

Konfigurimi A: agjenti ka qasje vetëm te logs
Konfigurimi B: agjenti ka qasje te të gjitha burimet
"""
import json
from agent import investigate

INCIDENT = (
    "Përdoruesit raportojnë se nuk mund të përfundojnë blerjen në dyqan. "
    "Gjej shkakun rrënjësor."
)

# Konfigurimi A - vetëm logs
print("\n" + "#" * 60)
print("# KONFIGURIMI A - vetëm logs")
print("#" * 60)

result_a = investigate(INCIDENT, allowed_tools=["get_service_logs"])

# Konfigurimi B - të gjitha burimet
print("\n" + "#" * 60)
print("# KONFIGURIMI B - të gjitha burimet")
print("#" * 60)

result_b = investigate(INCIDENT)

# Përmbledhje krahasuese
print("\n" + "=" * 60)
print("PËRMBLEDHJE")
print("=" * 60)
for name, r in [("A (vetëm logs)", result_a), ("B (të gjitha)", result_b)]:
    print(f"{name:20} | status: {r['status']:22} | "
          f"iteracione: {r['iterations']} | ${r['cost_usd']}")