import json, math, sys, time
from pathlib import Path
from .config import env

def main() -> int:
    """Return 0 when healthy, 1 otherwise"""

    path = Path(env.BOT_SETTINGS.HEALTH_STATE_FILE)

    try:
        state = json.loads(path.read_text())
        timestamp = float(state["timestamp"])
        latency = float(state["latency"])
    
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return 1

    age = time.time() - timestamp

    if age > env.BOT_SETTINGS.HEALTH_STALE_THRESHOLD:
        return 1
    if not math.isfinite(latency):
        return 1
    
    return 0

if __name__ == "__main__":
    raise SystemExit(main())