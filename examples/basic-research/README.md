# Basic Research Example

Minimize `score.txt` from `5.0` toward `0.0`. Each accepted hypothesis runs
`train.py` (decrement by one), then `eval.py`, which prints:

```json
{"metrics": {"score": <number>}}
```

The metric gate minimizes `score` against the current champion (baseline `5.0`
on a fresh project). Five accepted hypotheses take the champion from `5` → `0`.
Hypothesis `max_retries` covers execution failures; `max_hypotheses` bounds the
outer loop. Do not edit `eval.py`: it is protected.

Initialize this directory as a Git repository with its baseline committed on
`master`, set `AUTORESEARCH_PROJECT_ROOT` here, and save/run `research-loop.json`
through AutoResearch. Or use **New Project** in the UI to seed an equivalent
fixture into a fresh private GitHub repo.
