# Basic Research Example

This is a small target repository for the AutoResearch MVP. `score.txt` starts at `1.0`. The workflow runs `train.py`, which writes `0.5`, then `eval.py`, which prints the required evaluator result:

```json
{"metrics": {"score": 0.5}}
```

The included metric gate minimizes `score` against a baseline of `1.0`, so this candidate is accepted and merged into the target's `master` branch. To see a rejected trial, change `train.py` to write a value greater than or equal to the current champion score, such as `1.5`. Do not edit `eval.py`: it is protected and the run will fail before that evaluator executes.

Initialize this directory as a Git repository with its baseline committed on `master`, then set `AUTORESEARCH_PROJECT_ROOT` to this directory and save/run `research-loop.json` through AutoResearch.