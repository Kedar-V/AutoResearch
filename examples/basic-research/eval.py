import json
from pathlib import Path


score = float(Path("score.txt").read_text(encoding="utf-8"))
print(json.dumps({"metrics": {"score": score}}))