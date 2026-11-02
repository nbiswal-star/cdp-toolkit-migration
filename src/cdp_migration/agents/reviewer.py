"""Reviewer agent: explains blocked or flagged activities to IF staff in plain words.

It reads QA results only and has no tools. Without an LLM, a fixed template gives the same facts.
"""
from __future__ import annotations

import json

from ..state import StateStore

SYSTEM = """You help non-technical staff review website drafts. For each activity below, write two or three
short sentences: what the automatic check found, and exactly what the person should look at.
Use simple words. Do not suggest new wording for the activity. Do not guess beyond the data given."""


def review_items(state: StateStore) -> list[dict]:
    items = []
    for aid, st in sorted(state.activities.items()):
        if not st.activity:
            continue
        issues = []
        v, f, p = st.qa.get("validate", {}), st.qa.get("fidelity", {}), st.qa.get("pii", {})
        issues += [f"rule: {e}" for e in v.get("errors", [])]
        issues += [f"note: {w}" for w in v.get("warnings", [])]
        for c in f.get("changed", [])[:5]:
            issues.append(f"wording differs in {c['field']}: {' '.join(c.get('word_diff', [])[:12])}")
        for d in f.get("dropped", [])[:5]:
            issues.append(f"missing from {d['field']}: \"{d['source_text'][:100]}\"")
        issues += [f"numbers: {n}" for n in f.get("numbers", [])]
        issues += [f"flag: {x['kind']} in {x['field']}" for x in p.get("flags", [])]
        issues += [f"broken link: {b['url']} ({b['status']})" for b in (st.links or {}).get("broken", [])]
        blocked = st.post_id is None
        if issues or blocked:
            items.append({"activity_id": aid, "blocked": blocked, "issues": issues})
    return items


def template_summary(items: list[dict]) -> str:
    lines = []
    for it in items:
        head = "Not drafted yet" if it["blocked"] else "Drafted, please check"
        lines.append(f"- {it['activity_id']}: {head}.")
        lines += [f"    - {i}" for i in it["issues"][:8]]
    return "\n".join(lines) or "No activities need review."


def summarize(state: StateStore, llm=None) -> str:
    items = review_items(state)
    if not items or llm is None:
        return template_summary(items)
    resp = llm.complete(SYSTEM, [{"role": "user", "content": json.dumps(items, ensure_ascii=False)[:60000]}])
    return resp.text or template_summary(items)
