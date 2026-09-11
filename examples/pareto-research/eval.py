import json
from pathlib import Path


score = float(Path("score.txt").read_text(encoding="utf-8"))
cost_path = Path("cost.txt")
cost = float(cost_path.read_text(encoding="utf-8")) if cost_path.exists() else 0.0
print(json.dumps({"metrics": {"score": score, "cost": cost, "ok": 1}}))
