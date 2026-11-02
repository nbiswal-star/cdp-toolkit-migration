from __future__ import annotations

import csv
import difflib
import re
import unicodedata

from .. import wix
from ..guardrails import EMAIL, INJECTION, PHONE
from ..render import body_html, html_to_text
from .. import ricos
from ..ricos import links_in_blocks
from ..schema import Activity, activity_text_fields, blocks_text
from . import ToolContext, tool
from .extract import _update_qa_hash

def _plain(s: str) -> str:
    """Visible text: link markup removed and escaped brackets restored."""
    return ricos.unescape_link_text(ricos._LINK_MD.sub(lambda m: m.group(1), s))


def _key(s: str) -> str:
    """Comparison key for Activity text: link markup removed, then Unicode NFKC, all whitespace removed."""
    return _raw_key(_plain(s))


def _raw_key(s: str) -> str:
    """Comparison key for source text, which carries no link markup: NFKC, whitespace removed. Nothing else."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s))


def _groups(a: Activity) -> dict[str, list[str]]:
    """Activity text grouped the same way as the Wix source fields, one entry per line."""
    instr = blocks_text(a.setup).splitlines()
    for s in a.steps:
        instr.append(s.heading)
        instr += blocks_text(s.blocks).splitlines()
    return {
        "title": [f"{a.number} {a.title}".strip()], "description": [a.description], "goals": list(a.goals),
        "instructions": instr,
        "reflection_journal": blocks_text(a.reflection_journal).splitlines(),
        "practice_journal": blocks_text(a.practice_journal).splitlines(),
        "resources": blocks_text(a.resources).splitlines(),
    }


def _word_diff(new: str, candidates: list[str]) -> dict:
    best = max(candidates, key=lambda c: difflib.SequenceMatcher(None, c, new).ratio(), default="")
    diff = [d for d in difflib.ndiff(best.split(), _plain(new).split()) if d[:1] in "+-"]
    return {"activity_text": new[:300], "closest_source": best[:300], "word_diff": diff[:40]}


def fidelity_report(a: Activity, source: dict[str, str], document_mode: bool = False) -> dict:
    """Compare an Activity with its source. Shared by the tool and the evaluation harness."""
    changed, dropped = [], []
    total = found = 0
    groups = _groups(a)
    if document_mode:
        doc = source["document"]
        doc_key = _raw_key(doc)
        doc_lines = [ln.strip() for ln in doc.splitlines() if ln.strip()]
        for field, lines in groups.items():
            for ln in lines:
                if ln.strip() and _raw_key(ln) not in doc_key:  # extraction output is plain text
                    changed.append({"field": field, **_word_diff(ln, doc_lines)})
        act_key = _raw_key("\n".join(ln for lines in groups.values() for ln in lines))
        meta_words = set(re.findall(r"[a-z0-9]+", " ".join(
            [a.module_title, str(a.module_number), str(a.duration_minutes), a.level or ""] + a.tags).lower()))
        meta_words |= {"module", "duration", "minutes", "min", "level", "tags", "tag", "time"}
        for ln in doc_lines:
            if wix.is_label(ln) or len(_raw_key(ln)) < 4:
                continue
            total += 1
            words = set(re.findall(r"[a-z0-9]+", ln.lower()))
            if _raw_key(ln) in act_key or (words and words <= meta_words):
                found += 1
            else:
                dropped.append({"field": "document", "source_text": ln[:300]})
        coverage = found / total if total else 1.0
        numbers = []
        doc_nums = set(re.findall(r"\d+", doc))
        if a.duration_minutes is not None and str(a.duration_minutes) not in doc_nums:
            numbers.append(f"duration {a.duration_minutes} does not appear in the document")
        for word in [a.level or "", a.number] + a.tags:
            if word and word.lower() not in doc.lower():
                numbers.append(f"'{word}' does not appear in the document")
        ok = not changed and not numbers and not dropped
        return {"ok": ok, "coverage": round(coverage, 4), "changed": changed, "dropped": dropped, "numbers": numbers,
                "rule": "every activity line must appear in the document, and every document line must be used"}
    order = []
    for field, lines in groups.items():
        src = source.get(field, "")
        src_lines = [ln for ln in src.splitlines() if ln.strip()]
        if src_lines and wix.is_label(src_lines[0]):
            src_lines = src_lines[1:]  # the tab label ("Reflection Journal") is not content
        src_key = _raw_key("\n".join(src_lines))
        for ln in lines:
            if ln.strip() and _key(ln) not in src_key:
                changed.append({"field": field, **_word_diff(ln, src_lines)})
        act_key = _key("\n".join(lines))
        seen: dict[str, int] = {}
        for seg in src_lines:
            total += 1
            k = _raw_key(seg)
            seen[k] = seen.get(k, 0) + 1
            # Count occurrences, so losing one of two identical sentences is still caught.
            if act_key.count(k) >= min(seen[k], src_key.count(k)):
                found += 1
            else:
                dropped.append({"field": field, "source_text": seg[:300]})
        if act_key != src_key:  # same words but moved, swapped, or split differently
            order.append(field)
    numbers = []
    for s in a.steps:
        parsed = wix.parse_step_heading(s.heading)
        if not parsed or parsed[0] != s.number or parsed[1] != s.title or parsed[2] != s.minutes or parsed[3] != s.optional:
            numbers.append(f"step {s.number}: number, title, minutes, or optional flag do not match heading '{s.heading}'")
    if source.get("duration") is not None and str(a.duration_minutes) != str(source["duration"]):
        numbers.append(f"duration {a.duration_minutes} != source {source['duration']}")
    structure = []
    exp = source.get("structure")
    if exp is not None:
        got = activity_structure(a)
        for kind in ("links", "html", "images", "lists"):
            if got[kind] != exp[kind]:
                structure.append(f"{kind} differ from the source ({len(got[kind])} vs {len(exp[kind])}, or changed or reordered)")
    for name, want in (source.get("metadata") or {}).items():
        have = getattr(a, name)
        if have != want:
            structure.append(f"{name} is {have!r}, source says {want!r}")
    rendered = _raw_key(html_to_text(body_html(a)))
    not_rendered = [f"{f}: {t[:80]}" for f, t in activity_text_fields(a).items()
                    if f != "title" and t.strip() and any(_key(x) not in rendered for x in t.splitlines() if x.strip())]
    coverage = found / total if total else 1.0
    ok = not changed and not dropped and not order and not numbers and not structure and not not_rendered
    return {"ok": ok, "coverage": round(coverage, 4), "changed": changed, "dropped": dropped, "order": order,
            "numbers": numbers, "structure": structure, "not_rendered": not_rendered,
            "rule": "every field must equal the source in order, apart from whitespace; links, embeds, images, and metadata must match"}


def activity_structure(a: Activity) -> dict[str, list[str]]:
    links: list[str] = []
    htmls: list[str] = []
    images: list[str] = []
    lists: list[str] = []
    goal_blocks = [{"type": "paragraph", "text": g} for g in a.goals]
    blocks = goal_blocks + a.setup + [b for s in a.steps for b in s.blocks] + a.reflection_journal + a.practice_journal + a.resources
    for i, b in enumerate(blocks):
        if b["type"] == "callout":
            # The stored text and HTML must be exactly what the source box produces, so neither can be edited.
            src = b.get("source_html", "")
            card = ricos.html_card(src)
            same = card is not None and card["text"] == b.get("text") and card["html"] == b.get("html")
            htmls.append(src if same else "callout text or html does not match its source box")
            continue
        for text in [b.get("text", "")] + list(b.get("items", [])):
            links += [m.group(2) for m in ricos._LINK_MD.finditer(text)]
        if b["type"] == "list" and i >= len(goal_blocks):
            lists.append("ORDERED_LIST" if b.get("ordered") else "BULLETED_LIST")
        if b["type"] == "html":
            htmls.append(b.get("html", ""))
        if b["type"] == "image":
            images.append(f"{b['src']} | {b.get('alt', '')}")
    return {"links": links, "html": htmls, "images": images, "lists": lists}


@tool
def check_fidelity(ctx: ToolContext, activity_id: str) -> dict:
    """Verify that the Activity says exactly what the source says. Deterministic; no AI.

    Use after validate_activity. The source text is read again from the saved Wix record
    (or the submitted document) by a separate code path. Rules:
    - every line of every verbatim field (title, description, goals, set up, step
      headings and bodies, journals, resources) must appear in the source, character for
      character, ignoring only whitespace and Unicode normalization;
    - no source sentence may be missing, and each field must keep the source order;
    - links, embedded slides or video, images, level, tags, module, PDF, step numbers,
      step minutes, optional flags, and the activity duration must match the source exactly;
    - every verbatim line must appear in the rendered WordPress HTML.
    A failure blocks the activity and returns a word level diff for the human reviewer.
    Never try to fix a failure by editing the Activity yourself; report it.

    Args:
        activity_id: the activity to check.

    Returns:
        {"ok": bool, "coverage": float, "changed": [...], "dropped": [...], "numbers": [...]}
    """
    st = ctx.state.get(activity_id)
    a = ctx.state.activity(activity_id)
    if a is None:
        return {"error": "no Activity for this id; call extract_activity first"}
    if st.record is not None:
        src = wix.source_texts(st.record)
        src["duration"] = st.record.get("activityTime")
        src["structure"] = wix.source_structure(st.record)
        src["metadata"] = wix.record_metadata(st.record)
        rep = fidelity_report(a, src)
    elif st.document is not None:
        rep = fidelity_report(a, {"document": st.document}, document_mode=True)
    else:
        return {"error": "no source saved for this activity"}
    if not ctx.guardrails.fidelity_gate:
        rep = {**rep, "ok": True, "gate": "off"}
    st.qa["fidelity"] = rep
    _update_qa_hash(ctx, activity_id)
    return {k: (v[:10] if isinstance(v, list) else v) for k, v in rep.items()}


@tool
def scan_pii(ctx: ToolContext, activity_id: str) -> dict:
    """Flag personal data and text aimed at AI systems before anything is drafted.

    Use after check_fidelity. Flags: email addresses, phone numbers, names of people who
    commented on or rated the page (comments are never copied, so a match means a leak),
    and instruction-like text such as "ignore previous instructions" or "publish this page
    live". Flagged text is kept verbatim and the activity is sent to a person; it is never
    deleted or acted on. The credited contributor ("Submitted By ...") is public and is
    not flagged.

    Args:
        activity_id: the activity to scan.

    Returns:
        {"ok": bool, "flags": [{"field", "kind", "snippet"}]}
    """
    a = ctx.state.activity(activity_id)
    if a is None:
        return {"error": "no Activity for this id; call extract_activity first"}
    st = ctx.state.get(activity_id)
    flags = pii_flags(a, st.commenter_names)
    ok = not flags or not ctx.guardrails.pii_gate
    st.qa["pii"] = {"ok": ok, "flags": flags}
    _update_qa_hash(ctx, activity_id)
    return st.qa["pii"]


def pii_flags(a: Activity, names: list[str]) -> list[dict]:
    flags = []
    for field, text in activity_text_fields(a).items():
        for m in EMAIL.finditer(text):
            flags.append({"field": field, "kind": "email", "snippet": m.group(0)[:2] + "***"})
        for m in PHONE.finditer(text):
            flags.append({"field": field, "kind": "phone", "snippet": "***" + m.group(0)[-4:]})
        for n in names:
            if n and re.search(rf"\b{re.escape(n)}\b", text, re.I) and n != a.contributor:
                flags.append({"field": field, "kind": "commenter_name", "snippet": n[:1] + "***"})
        for m in INJECTION.finditer(text):
            flags.append({"field": field, "kind": "instruction_like_text", "snippet": m.group(0)[:80]})
    return flags


@tool
def check_links(ctx: ToolContext, activity_id: str) -> dict:
    """Check every link and file in an activity and record its old to new address.

    Use after create_draft. Checks each link's status without downloading it (public http
    and https addresses only; email and phone links are listed as not checked) and reports
    any that do not answer HTTP 200. Records the redirect from the old Toolkit address
    (/items-1/<activity_id>) to the activity's planned permalink and rewrites
    out/redirects.csv for the WordPress Redirection plugin. Import it after IF publishes the
    pages, in a Redirection group that matches the old domain only.

    Args:
        activity_id: the activity to check.

    Returns:
        {"checked": int, "broken": [{"url", "status"}], "redirect": {"source", "target"} or null}
    """
    a = ctx.state.activity(activity_id)
    if a is None:
        return {"error": "no Activity for this id; call extract_activity first"}
    st = ctx.state.get(activity_id)
    blocks = a.setup + [b for s in a.steps for b in s.blocks] + a.reflection_journal + a.practice_journal + a.resources
    urls = sorted(set(links_in_blocks(blocks) + [u for u in (a.pdf_url, a.image_url) if u]
                      + [m.group(2) for g in a.goals for m in re.finditer(r"\[([^\]]+)\]\(([^)\s]+)\)", g)]))
    fetch = ctx.link_fetcher or ctx.fetcher
    broken, unchecked = [], []
    for u in urls:
        try:
            status = fetch.get(u)[0]
        except Exception as e:  # noqa: BLE001
            status = f"{type(e).__name__}"
        if status == "not checked":
            unchecked.append(u)
        elif status != 200:
            broken.append({"url": u, "status": status})
    redirect = None
    if st.post_id is not None:
        # Target is the planned public permalink, valid once IF publishes the page.
        redirect = {"source": f"/items-1/{activity_id}", "target": f"{ctx.permalink_base}{activity_id}/"}
    st.links = {"checked": len(urls) - len(unchecked), "broken": broken, "not_checked": unchecked, "redirect": redirect}
    _write_redirects(ctx)
    return st.links


def _write_redirects(ctx: ToolContext) -> None:
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    rows = [st.links["redirect"] for st in ctx.state.activities.values()
            if st.links and st.links.get("redirect")]
    with open(ctx.out_dir / "redirects.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "target", "regex", "code"])
        for r in sorted(rows, key=lambda r: r["source"]):
            w.writerow([r["source"], r["target"], 0, 301])
