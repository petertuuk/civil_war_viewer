"""Headline numbers of a script, kept as data instead of only printed (roadmap T1.2).

    from metrics import record
    record("fast_jumps", stats=dict(stats), rows=len(rows))      # -> data/scores/metrics/fast_jumps.json

One small JSON file per script (keys sorted, values numbers or dicts of numbers), rewritten on every run, so two builds can be
compared with metrics_diff.py and a regression shows up as a changed number rather than a stage that quietly stopped. The directory
is data/scores/metrics under the current directory (rebuild.sh runs from the project folder); CWV_METRICS_DIR overrides it.
Recording never stops a build: a failure to write is reported and ignored.
"""
import json
import os
from pathlib import Path


def record(script, **counts):
    try:
        d = Path(os.environ.get("CWV_METRICS_DIR", "data/scores/metrics"))
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{script}.json").write_text(json.dumps(counts, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception as e:      # a metrics file must never fail a rebuild
        print(f"metrics: {script} not written ({e})")
