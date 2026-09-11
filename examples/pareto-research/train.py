"""Toy trainer: lowers score and reports a second cost metric (bytes written)."""

from pathlib import Path

path = Path("score.txt")
current = float(path.read_text(encoding="utf-8"))
next_score = max(current - 1, 0)
path.write_text(f"{next_score}\n", encoding="utf-8")
# Side cost grows as we chase the score (forces a tradeoff vs score).
Path("cost.txt").write_text(f"{(5 - next_score) * 10}\n", encoding="utf-8")
