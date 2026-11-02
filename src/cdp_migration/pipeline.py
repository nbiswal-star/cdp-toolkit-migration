"""Fixed-order pipeline over the same tools the agent uses. Runs without any LLM."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import tools as T

STEPS = ("fetch_page", "extract_activity", "validate_activity", "check_fidelity", "scan_pii",
         "rehost_asset", "create_draft", "check_links")


@dataclass
class PipelineResult:
    drafted: list[str] = field(default_factory=list)
    review: dict[str, str] = field(default_factory=dict)     # activity_id -> first blocking reason
    warnings: dict[str, list[str]] = field(default_factory=dict)
    broken_links: dict[str, list[dict]] = field(default_factory=dict)


def migrate(ctx: T.ToolContext, only: list[str] | None = None, limit: int | None = None) -> PipelineResult:
    inv = T.call(ctx, "crawl_toolkit", {})
    ids = [a["activity_id"] for a in inv.get("activities", [])]
    if only:
        ids = [i for i in ids if i in only]
    if limit:
        ids = ids[:limit]
    res = PipelineResult()
    for aid in ids:
        for step in STEPS:
            out = T.call(ctx, step, {"activity_id": aid})
            if "error" in out:
                res.review[aid] = f"{step}: {out['error']}"
                break
            if step == "validate_activity" and out.get("warnings"):
                res.warnings[aid] = out["warnings"]
            if step in ("validate_activity", "check_fidelity", "scan_pii") and not out.get("ok", True):
                # Keep going through the checks so the reviewer sees every problem; create_draft will refuse.
                res.review.setdefault(aid, f"{step} failed")
            if step == "scan_pii" and aid in res.review:
                a = ctx.state.activity(aid)
                if a and ctx.state.get(aid).human_approved_hash == a.content_hash():
                    del res.review[aid]  # a person approved this exact version
                else:
                    break  # blocked: no media upload and no draft until a person reviews it
            if step == "check_links" and out.get("broken"):
                res.broken_links[aid] = out["broken"]
        if aid not in res.review:
            res.drafted.append(aid)
    return res


def approve(ctx: T.ToolContext, activity_id: str) -> str:
    """Record a person's approval of the current version. Only the CLI calls this, never the agent."""
    a = ctx.state.activity(activity_id)
    if a is None:
        raise KeyError(f"no Activity for {activity_id}")
    st = ctx.state.get(activity_id)
    st.human_approved_hash = a.content_hash()
    ctx.state.save()
    return st.human_approved_hash
