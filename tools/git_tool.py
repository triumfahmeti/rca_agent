
import subprocess

from config import GIT_REPO_PATH


def get_recent_commits(since_hours: int = 24, path_filter: str = None,
                        max_commits: int = 15) -> dict:
    cmd = [
        "git", "-C", GIT_REPO_PATH, "log",
        f"--since={since_hours}.hours.ago",
        f"--max-count={max_commits}",
        # Formati: hash|autor|datë relative|datë absolute|mesazh
        "--pretty=format:%h|%an|%ar|%aI|%s",
    ]

    if path_filter:
        cmd.extend(["--", path_filter])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15, check=True
        )
    except subprocess.CalledProcessError as e:
        return {"status": "error", "error": f"git dështoi: {e.stderr}", "commits": []}
    except FileNotFoundError:
        return {"status": "error", "error": "git nuk u gjet në sistem", "commits": []}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "git timeout", "commits": []}

    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split("|", 4)
        if len(parts) == 5:
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "when": parts[2],          
                "timestamp": parts[3],     
                "message": parts[4],
            })

    
    if commits:
        note = (
            f"U gjetën {len(commits)} commits në {since_hours} orët e fundit"
            + (f" që prekin '{path_filter}'." if path_filter else ".")
            + " Krahaso kohën e këtyre commits me momentin kur filloi incidenti. "
            "Një commit pak para fillimit të incidentit është sinjal i fortë."
        )
    else:
        note = (
            f"Asnjë commit në {since_hours} orët e fundit"
            + (f" që prek '{path_filter}'." if path_filter else ".")
            + " Kjo e bën më pak të mundshme që incidenti të jetë shkaktuar "
            "nga një ndryshim i fundit kodi."
        )

    return {
        "status": "ok",
        "since_hours": since_hours,
        "path_filter": path_filter,
        "count": len(commits),
        "commits": commits,
        "note": note,
    }