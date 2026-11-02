"""Read Toolkit activities from Wix pages.

Every Toolkit activity page (/items-1/<slug>) embeds its Wix CMS record in a
<script id="wix-warmup-data"> JSON block at
appsWarmupData.dataBinding.dataStore.recordsByCollectionId.Items1.
We map that record to an Activity field by field, so activity wording is copied, not re-typed.

Ratings and comments (collections "comments" and "CommentRatings") are never copied.
Commenter names are collected only so the PII check can confirm none leaked into a page.
"""
from __future__ import annotations

import html
import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

from . import ricos
from .schema import KNOWN_TAGS, LEVELS, Activity, Block, Step

SITE = "https://www.collaborativediscussionproject.com"
ITEM_PATH = re.compile(r"/items-1/[a-z0-9]+")

_NUM_WORDS = {w: i for i, w in enumerate(
    ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
     "sixteen seventeen eighteen nineteen twenty").split())}
STEP_HEADING = re.compile(
    r"^\s*Step\s+(?P<num>\w+)\s*(?P<opt>\(optional\))?\s*:\s*(?P<title>.+?)\s*$", re.I)
STEP_MINUTES = re.compile(r"\((?P<min>\d+)(?:\s*(?:-|to|–)\s*(?P<max>\d+))?\s*min(?:ute)?s?\.?\)\s*$", re.I)
STEP_OPTIONAL_SUFFIX = re.compile(r"\s*\(optional\)\s*$", re.I)
SETUP_HEADING = re.compile(r"^\s*Set\s*Up\b", re.I)
UI_LABELS = {"instructions", "learning goals", "reflection journal", "practice journal",
             "additional resources", "activity cluster"}


class WixPageError(ValueError):
    pass


class _WarmupFinder(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in = False
        self.data: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "wix-warmup-data":
            self._in = True

    def handle_endtag(self, tag):
        if tag == "script":
            self._in = False

    def handle_data(self, data):
        if self._in:
            self.data.append(data)


def warmup_data(page_html: str) -> dict[str, Any]:
    f = _WarmupFinder()
    f.feed(page_html)
    if not f.data:
        raise WixPageError("No wix-warmup-data block on the page")
    return json.loads("".join(f.data))


def collections(page_html: str) -> dict[str, dict[str, Any]]:
    w = warmup_data(page_html)
    try:
        return w["appsWarmupData"]["dataBinding"]["dataStore"]["recordsByCollectionId"]
    except (KeyError, TypeError) as e:
        raise WixPageError("Warmup data has no dataStore records") from e


def activity_record(page_html: str) -> dict[str, Any]:
    items = collections(page_html).get("Items1") or {}
    if len(items) != 1:
        raise WixPageError(f"Expected one Items1 record, found {len(items)}")
    return next(iter(items.values()))


def commenter_names(page_html: str) -> set[str]:
    """Names of people who rated or commented. Used only as a PII deny list."""
    names: set[str] = set()
    cols = collections(page_html)

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and re.search(r"name|author", k, re.I) and 2 < len(v.strip()) < 80:
                    names.add(v.strip())
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for key in ("comments", "CommentRatings"):
        walk(cols.get(key) or {})
    return names


def item_paths(module_page_html: str) -> list[str]:
    seen: list[str] = []
    for m in ITEM_PATH.finditer(module_page_html):
        if m.group(0) not in seen:
            seen.append(m.group(0))
    return seen


def wix_document_url(value: str | None) -> str | None:
    """wix:document://v1/ugd/<file>.pdf/<name> -> public file URL."""
    if not value:
        return None
    m = re.match(r"wix:document://v1/ugd/([^/]+)", value)
    return f"{SITE}/_files/ugd/{m.group(1)}" if m else value


def wix_image_url(value: str | None) -> str | None:
    """wix:image://v1/<id>/<name>#... -> original image URL (no resize parameters)."""
    if not value:
        return None
    m = re.match(r"wix:image://v1/([^/#]+)", value)
    return f"https://static.wixstatic.com/media/{quote(m.group(1))}" if m else value


def _norm_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def parse_step_heading(text: str) -> tuple[int, str, int | None, bool] | None:
    m = STEP_HEADING.match(_norm_heading(text))
    if not m:
        return None
    raw = m.group("num").lower()
    num = int(raw) if raw.isdigit() else _NUM_WORDS.get(raw)
    if num is None:
        return None
    title = m.group("title")
    mm = STEP_MINUTES.search(title)
    # A range such as "(10-15 min)" is kept in the heading; the step's minutes count as the upper end.
    minutes = int(mm.group("max") or mm.group("min")) if mm else None
    if mm:
        title = title[:mm.start()].rstrip()
    optional = bool(m.group("opt"))
    if STEP_OPTIONAL_SUFFIX.search(title):
        title, optional = STEP_OPTIONAL_SUFFIX.sub("", title), True
    return num, title, minutes, optional


def is_label(text: str) -> bool:
    return text.strip().strip(":").strip().lower() in UI_LABELS


def _strip_label(blocks: list[Block]) -> list[Block]:
    """Drop a leading tab label such as "Reflection Journal" (heading or bold paragraph)."""
    if blocks and blocks[0]["type"] in ("heading", "paragraph") and is_label(blocks[0]["text"]):
        return blocks[1:]
    return blocks


def split_instructions(blocks: list[Block]) -> tuple[list[Block], list[Step]]:
    blocks = _strip_label(blocks)
    setup: list[Block] = []
    steps: list[Step] = []
    for b in blocks:
        parsed = parse_step_heading(b["text"]) if b["type"] == "heading" else None
        if parsed:
            num, title, minutes, optional = parsed
            steps.append(Step(number=num, title=title, minutes=minutes, optional=optional,
                              heading=_norm_heading(b["text"]), blocks=[]))
        elif steps:
            steps[-1].blocks.append(b)
        else:
            setup.append(b)
    return setup, steps


def _goals(blocks: list[Block]) -> list[str]:
    goals: list[str] = []
    for b in _strip_label(blocks):
        if b["type"] == "list":
            goals.extend(i.strip() for i in b["items"])
        elif b["type"] in ("paragraph", "heading"):
            goals.append(b["text"].strip())
    return [g for g in goals if g]


def record_to_activity(rec: dict[str, Any], source_url: str | None = None) -> Activity:
    """Deterministic mapping of one Wix Items1 record to an Activity."""
    raw_title = _norm_heading(rec.get("title", ""))
    m = re.match(r"^(\d+\.\d+)\s+(.*)$", raw_title)
    number, title = (m.group(1), m.group(2)) if m else ("", raw_title)
    mod = re.search(r"(\d+)", rec.get("module", "") or "")
    icons = rec.get("activityIcons") or []
    level = next((i.get("title") for i in icons if i.get("title") in LEVELS), None)
    tags = [i.get("title") for i in icons if i.get("title") and i.get("title") not in LEVELS]
    setup, steps = split_instructions(ricos.to_blocks(rec.get("activityInstructions")))
    contributor = rec.get("activityContributor")
    if contributor:
        contributor = re.sub(r"^\s*Submitted\s+By\s+", "", contributor, flags=re.I).strip()
    slug = rec.get("urlNoSpaceText") or (rec.get("link-items-1-title", "").rsplit("/", 1)[-1])
    updated = rec.get("_updatedDate")
    return Activity(
        activity_id=slug,
        number=number,
        title=title,
        module_number=int(mod.group(1)) if mod else 0,
        module_title=rec.get("activityPageModuleTitle", "") or "",
        description=(rec.get("activityDescription") or "").strip(),
        duration_minutes=rec.get("activityTime"),
        level=level,
        tags=tags,
        goals=_goals(ricos.to_blocks(rec.get("activityGoals"))),
        setup=setup,
        steps=steps,
        reflection_journal=_strip_label(ricos.to_blocks(rec.get("activityReflectionJournal"))),
        practice_journal=_strip_label(ricos.to_blocks(rec.get("activityPracticeJournal"))),
        resources=_strip_label(ricos.to_blocks(rec.get("activityResources"))),
        contributor=contributor,
        pdf_url=wix_document_url(rec.get("activityPdf")) or rec.get("activityPdfUrl"),
        image_url=wix_image_url(rec.get("activityImage")),
        image_alt=rec.get("activityImageAltText"),
        image_credit=rec.get("activityImageCredit"),
        tag_notes={i["title"]: i.get("description", "") for i in icons if i.get("title")},
        source_url=source_url or (SITE + rec["link-items-1-title"] if rec.get("link-items-1-title") else None),
        source_updated=updated.get("$date") if isinstance(updated, dict) else updated,
    )


def unknown_tags(a: Activity) -> list[str]:
    return [t for t in a.tags if t not in KNOWN_TAGS]


def source_texts(rec: dict[str, Any]) -> dict[str, str]:
    """Independent plain text view of the source record, field by field.

    This deliberately does not reuse the Activity mapping, so the fidelity check compares
    two separate paths through the data.
    """
    def html_text(h: str) -> list[str]:
        h = re.sub(r"(?s)<!--.*?-->", " ", h or "")
        h = re.sub(r"(?is)<(head|style|script|title)\b.*?</\1\s*>", " ", h)
        h = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6])\s*>", "\n", h)
        h = re.sub(r"<[^>]+>", "", h)
        return [ln for ln in html.unescape(h).splitlines() if ln.strip()]

    def all_text(node: Any) -> list[str]:
        out: list[str] = []
        if isinstance(node, dict):
            if node.get("type") == "HTML" and "<iframe" not in ((node.get("htmlData") or {}).get("html") or "").lower():
                return html_text((node.get("htmlData") or {}).get("html") or "")
            if node.get("type") == "TEXT":
                t = (node.get("textData") or {}).get("text", "")
                if t.strip():
                    out.append(t)
            for k, v in node.items():
                if k != "textData":
                    out.extend(all_text(v))
        elif isinstance(node, list):
            for v in node:
                out.extend(all_text(v))
        return out

    texts = {
        "title": rec.get("title", ""),
        "description": rec.get("activityDescription", "") or "",
    }
    for key, field in (("activityGoals", "goals"), ("activityInstructions", "instructions"),
                       ("activityReflectionJournal", "reflection_journal"),
                       ("activityPracticeJournal", "practice_journal"),
                       ("activityResources", "resources")):
        texts[field] = "\n".join(all_text(rec.get(key)))
    return texts


def source_structure(rec: dict[str, Any]) -> dict[str, list[str]]:
    """Ordered link URLs, embedded HTML, and image sources in the record, read independently of the mapping."""
    links: list[str] = []
    htmls: list[str] = []
    images: list[str] = []
    lists: list[str] = []

    def walk(n: Any, count_lists: bool = True) -> None:
        if isinstance(n, dict):
            if count_lists and n.get("type") in ("BULLETED_LIST", "ORDERED_LIST"):
                lists.append(n["type"])
            if n.get("type") == "TEXT":
                td = n.get("textData") or {}
                for d in td.get("decorations") or []:
                    url = (((d.get("linkData") or {}).get("link") or {}).get("url"))
                    if d.get("type") == "LINK" and url and td.get("text", "").strip():
                        links.append(ricos.md_link("x", url)[4:-1])
                return
            if n.get("type") == "HTML":
                hd = n.get("htmlData") or {}
                htmls.append(hd.get("html") or hd.get("url") or "")
            if n.get("type") == "IMAGE":
                src = ricos._image_src(n)
                if src:
                    images.append(f"{src} | {(n.get('imageData') or {}).get('altText') or ''}")
            # Nested lists are flattened into their parent list by the mapping, so only top-level lists count.
            inner = count_lists and n.get("type") not in ("BULLETED_LIST", "ORDERED_LIST")
            for v in n.values():
                walk(v, inner)
        elif isinstance(n, list):
            for v in n:
                walk(v, count_lists)

    # Goals become a plain list of strings, so their list kind is not compared.
    for key in ("activityGoals", "activityInstructions", "activityReflectionJournal",
                "activityPracticeJournal", "activityResources"):
        walk(rec.get(key), key != "activityGoals")
    return {"links": links, "html": htmls, "images": images, "lists": lists}


def record_metadata(rec: dict[str, Any]) -> dict[str, Any]:
    """Metadata straight from the raw record, written separately from record_to_activity."""
    icons = [i.get("title") for i in (rec.get("activityIcons") or []) if i.get("title")]
    title = re.sub(r"\s+", " ", rec.get("title", "")).strip()
    contributor = (rec.get("activityContributor") or "").strip()
    if contributor.lower().startswith("submitted by "):
        contributor = contributor[len("submitted by "):].strip()
    pdf = rec.get("activityPdf") or ""
    pdf_url = (SITE + "/_files/ugd/" + pdf.split("/ugd/", 1)[1].split("/", 1)[0]) if "/ugd/" in pdf \
        else (rec.get("activityPdfUrl") or None)
    img = rec.get("activityImage") or ""
    img_url = ("https://static.wixstatic.com/media/" + quote(img[len("wix:image://v1/"):].split("/", 1)[0].split("#", 1)[0])) \
        if img.startswith("wix:image://v1/") else (img or None)
    return {
        "number": title.split(" ", 1)[0] if re.match(r"^\d+\.\d+ ", title) else "",
        "module_number": int(re.sub(r"\D", "", rec.get("module", "") or "") or 0),
        "module_title": rec.get("activityPageModuleTitle", "") or "",
        "level": next((t for t in icons if t in ("Beginner", "Advanced")), None),
        "tags": [t for t in icons if t not in ("Beginner", "Advanced")],
        "contributor": contributor or None,
        "pdf_url": pdf_url,
        "image_url": img_url,
        "image_alt": rec.get("activityImageAltText"),
        "image_credit": rec.get("activityImageCredit"),
        "duration_minutes": rec.get("activityTime"),
    }
