from pathlib import Path

path = Path("score.txt")
current = float(path.read_text(encoding="utf-8"))
path.write_text(f"{max(current - 1, 0)}\n", encoding="utf-8")
