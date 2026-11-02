from __future__ import annotations

import hashlib
import mimetypes
import re
from urllib.parse import unquote, urlparse

from . import ToolContext, tool


def _gate(ctx: ToolContext, activity_id: str) -> str | None:
    """None when this exact Activity version passed every check or was approved by a person."""
    st = ctx.state.get(activity_id)
    a = ctx.state.activity(activity_id)
    if not ctx.guardrails.approval_gate:
        return None
    if a.content_hash() in (st.qa_hash, st.human_approved_hash):
        return None
    failed = [k for k in ("validate", "fidelity", "pii") if not st.qa.get(k, {}).get("ok")]
    why = f"checks not passed: {failed}" if failed else "record changed after the checks passed"
    return f"blocked: {why}. A person must review it (cdp review / cdp approve)."


@tool
def rehost_asset(ctx: ToolContext, activity_id: str) -> dict:
    """Copy the activity's PDF, main image, and any images inside its text to the WordPress media library.

    Use after validate_activity, check_fidelity, and scan_pii have passed, and before
    create_draft. Same precondition as create_draft, enforced in code: uploaded files are
    public, so nothing is uploaded for an activity that has not passed its checks.
    Downloads the original files (never Wix resized copies), hashes each with SHA-256, and
    uploads each file only once: a file already uploaded in any earlier run is reused. Wix
    file links stop working when the Wix plan ends, so every activity file is re-hosted.

    Args:
        activity_id: the activity whose files to copy.

    Returns:
        {"pdf": {"id", "url"} or null, "image": {"id", "url"} or null, "inline_images": int,
         "reused": int} or {"error": str}.
    """
    a = ctx.state.activity(activity_id)
    if a is None:
        return {"error": "no Activity for this id; call extract_activity first"}
    blocked = _gate(ctx, activity_id)
    if blocked:
        return {"error": blocked}
    st = ctx.state.get(activity_id)
    blocks = a.setup + [b for s in a.steps for b in s.blocks] + a.reflection_journal + a.practice_journal + a.resources
    wanted = [("pdf", a.pdf_url), ("image", a.image_url)]
    wanted += [(f"inline:{b['src']}", b["src"]) for b in blocks if b["type"] == "image"]
    out, reused = {"pdf": None, "image": None}, 0
    for kind, url in wanted:
        if not url:
            continue
        status, ctype, data = ctx.fetcher.get(url)
        if status != 200:
            return {"error": f"HTTP {status} downloading {kind} {url}"}
        sha = hashlib.sha256(data).hexdigest()
        if sha in ctx.state.media:
            m, reused = ctx.state.media[sha], reused + 1
        else:
            name = unquote(urlparse(url).path.rsplit("/", 1)[-1]) or f"{activity_id}-file"
            name = re.sub(r"[^A-Za-z0-9._-]", "-", name)[:100]
            if "." not in name:
                name += mimetypes.guess_extension(ctype or "") or ""
            up = ctx.adapter.upload_media(f"{activity_id}-{name}", data, ctype)
            m = ctx.state.media[sha] = {"id": up["id"], "url": up["url"], "source": url}
        st.media[kind] = sha
        if kind in out:
            out[kind] = m
    return {**out, "inline_images": sum(k.startswith("inline:") for k in st.media), "reused": reused}


@tool
def create_draft(ctx: ToolContext, activity_id: str) -> dict:
    """Create or update the single WordPress DRAFT for one activity.

    Preconditions, enforced in code: validate_activity, check_fidelity, and scan_pii have
    all passed for this activity and its record is unchanged since then (hash check), or a
    person has approved this exact version with `cdp approve`. The tool takes only the
    activity_id: it loads the approved record itself, so content cannot change between the
    checks and the draft. Status is always "draft"; this tool cannot publish, and the
    WordPress account it uses has no publish permission. An activity already published on
    WordPress is never overwritten.

    Args:
        activity_id: the activity to draft.

    Returns:
        {"post_id", "draft_url", "status": "draft"} or {"error": str}. On error, do not
        retry more than twice; report the activity for human review.
    """
    a = ctx.state.activity(activity_id)
    if a is None:
        return {"error": "no Activity for this id; call extract_activity first"}
    st = ctx.state.get(activity_id)
    blocked = _gate(ctx, activity_id)
    if blocked:
        return {"error": blocked}
    media = {kind: ctx.state.media[sha] for kind, sha in st.media.items() if sha in ctx.state.media}
    status = "draft"
    res = ctx.adapter.upsert_draft(a, media, status=status, post_id=st.post_id)
    st.post_id, st.draft_url = res["post_id"], res["url"]
    return {"post_id": res["post_id"], "draft_url": res["url"], "status": res["status"]}
