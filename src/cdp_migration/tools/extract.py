from __future__ import annotations

import re

from .. import ricos, wix
from ..schema import LEVELS, Activity
from . import ToolContext, tool


def _update_qa_hash(ctx: ToolContext, activity_id: str) -> None:
    """Record the content hash only when validation, fidelity, and PII checks all passed."""
    st = ctx.state.get(activity_id)
    a = ctx.state.activity(activity_id)
    checks = [st.qa.get(k, {}).get("ok") for k in ("validate", "fidelity", "pii")]
    st.qa_hash = a.content_hash() if a and all(checks) else None


@tool
def extract_activity(ctx: ToolContext, activity_id: str, document_text: str | None = None) -> dict:
    """Build the structured Activity record for one activity from its saved Wix record.

    Maps the Wix record saved by fetch_page to the Activity fields one by one. No AI is
    involved and every word is copied exactly. Call fetch_page first. Any earlier QA result
    for this activity is cleared, so validate_activity, check_fidelity, and scan_pii must
    run again before create_draft. (New activities written as documents are handled by the
    separate `cdp new-activity` command, not by you.)

    Args:
        activity_id: the activity to extract.

    Returns:
        {"activity_id", "number", "title", "steps": int, "duration_minutes", "level", "tags"}
        or {"error": str}.
    """
    st = ctx.state.get(activity_id)
    if document_text is not None:
        if not ctx.allow_document_mode:
            return {"error": "document mode is only available through the `cdp new-activity` command"}
        if st.record is not None:
            return {"error": "this activity_id belongs to a migrated Toolkit page; use a new activity_id"}
        if ctx.llm is None:
            return {"error": "document mode needs an LLM (set ANTHROPIC_API_KEY)"}
        from ..agents.extraction import extract_from_document

        a = extract_from_document(ctx.llm, activity_id, document_text)
        st.document, st.record = document_text, None
    else:
        if not st.record:
            return {"error": "no record saved for this activity; call fetch_page first"}
        a = wix.record_to_activity(st.record, source_url=st.url)
        a.activity_id = activity_id
    st.activity = a.to_dict()
    st.qa, st.qa_hash = {}, None
    return {"activity_id": activity_id, "number": a.number, "title": a.title, "steps": len(a.steps),
            "duration_minutes": a.duration_minutes, "level": a.level, "tags": a.tags}


@tool
def validate_activity(ctx: ToolContext, activity_id: str) -> dict:
    """Check an extracted Activity against the Toolkit rules. Deterministic; no AI.

    Use after extract_activity. Errors block the activity; warnings go to the human
    reviewer but do not block. Rules: number like "2.6"; non-empty title and description;
    module 1 to 5; duration 5 to 240 minutes; level Beginner or Advanced; at least one
    learning goal; at least two steps numbered 1, 2, 3 in order. Warnings: step minutes
    that do not add up to within 15 minutes of the duration, unknown tags, embedded HTML
    (slides, video) that a person must check, and a missing PDF.

    Args:
        activity_id: the activity to check.

    Returns:
        {"ok": bool, "errors": [str], "warnings": [str]}
    """
    a = ctx.state.activity(activity_id)
    if a is None:
        return {"error": "no Activity for this id; call extract_activity first"}
    errors, warnings = _rules(a)
    st = ctx.state.get(activity_id)
    st.qa["validate"] = {"ok": not errors, "errors": errors, "warnings": warnings}
    _update_qa_hash(ctx, activity_id)
    return st.qa["validate"]


def _rules(a: Activity) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not re.fullmatch(r"\d+\.\d+", a.number or ""):
        errors.append(f"number '{a.number}' is not like '2.6'")
    if not a.title.strip():
        errors.append("title is empty")
    if not a.description.strip():
        errors.append("description is empty")
    if a.module_number not in (1, 2, 3, 4, 5):
        errors.append(f"module {a.module_number} is not 1 to 5")
    elif a.number and not a.number.startswith(f"{a.module_number}."):
        errors.append(f"number {a.number} does not match module {a.module_number}")
    if not isinstance(a.duration_minutes, int) or not 5 <= a.duration_minutes <= 240:
        errors.append(f"duration {a.duration_minutes} is not 5 to 240 minutes")
    if a.level not in LEVELS:
        errors.append(f"level {a.level} is not Beginner or Advanced")
    if not a.goals:
        errors.append("no learning goals")
    if len(a.steps) < 2:
        errors.append(f"only {len(a.steps)} steps found")
    nums = [s.number for s in a.steps]
    if nums != list(range(1, len(nums) + 1)):
        errors.append(f"steps are numbered {nums}, expected 1 to {len(nums)}")
    mins = [s.minutes for s in a.steps if s.minutes is not None]
    if isinstance(a.duration_minutes, int) and mins and abs(sum(mins) - a.duration_minutes) > 15:
        warnings.append(f"step minutes add up to {sum(mins)}, duration is {a.duration_minutes}")
    unknown = wix.unknown_tags(a)
    if unknown:
        warnings.append(f"unknown tags {unknown}")
    blocks = a.setup + [b for s in a.steps for b in s.blocks] + a.reflection_journal + a.practice_journal + a.resources
    for b in blocks:
        if b["type"] == "heading" and re.match(r"\s*Step\b", b.get("text", ""), re.I):
            errors.append(f"heading '{b['text'][:60]}' looks like a step but could not be read as one")
        if b["type"] == "unsupported":
            errors.append(f"unsupported {b['node']} content must be added by hand")
        if b["type"] == "html":
            reason = ricos.unsafe_embed_reason(b.get("html", ""))
            if reason:
                errors.append(f"{reason}; a person must decide how to show it")
    n_html = sum(b["type"] == "html" for b in blocks)
    if n_html:
        warnings.append(f"{n_html} embedded HTML block(s) (slides or video) need a person to check")
    if not a.pdf_url:
        warnings.append("no PDF linked")
    return errors, warnings
