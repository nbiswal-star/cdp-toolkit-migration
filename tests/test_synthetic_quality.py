"""Synthetic data must stay inside the structure measured on the live Toolkit (eval/live_structure_2026-11-01.json)."""
import json
from collections import Counter
from pathlib import Path

from cdp_migration import synthetic, wix

LIVE = json.loads((Path(__file__).resolve().parents[1] / "eval" / "live_structure_2026-11-01.json").read_text())


def test_synthetic_matches_live_structure():
    live = LIVE["activities"]
    acts = [wix.record_to_activity(r) for r in synthetic.make_toolkit(seed=7)]
    assert Counter(str(a.module_number) for a in acts) == Counter(LIVE["module_sizes"]) or \
        {str(k): v for k, v in Counter(a.module_number for a in acts).items()} == LIVE["module_sizes"]
    lo, hi = min(x["duration_minutes"] for x in live), max(x["duration_minutes"] for x in live)
    assert all(lo <= a.duration_minutes <= hi for a in acts)
    smin, smax = min(x["steps"] for x in live), max(x["steps"] for x in live)
    assert all(smin <= len(a.steps) <= smax for a in acts)
    live_tags = {t for x in live for t in x["tags"]}
    assert {t for a in acts for t in a.tags} <= live_tags
    assert all(a.level in ("Beginner", "Advanced") for a in acts)
    assert all(sum(s.minutes for s in a.steps) == a.duration_minutes for a in acts)


def test_synthetic_uses_only_live_node_types():
    allowed = set(LIVE["rich_text_node_types"]) | {"TEXT"}
    seen = set()

    def walk(n):
        if isinstance(n, dict):
            if "type" in n and n["type"] not in ("LINK",):
                seen.add(n["type"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    for r in synthetic.make_toolkit(seed=7):
        for k in ("activityGoals", "activityInstructions", "activityReflectionJournal",
                  "activityPracticeJournal", "activityResources"):
            walk(r[k])
    seen -= {"image"}  # icon dicts, not rich text
    assert seen <= allowed, seen - allowed
