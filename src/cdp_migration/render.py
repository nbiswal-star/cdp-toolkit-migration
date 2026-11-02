"""Render an Activity for WordPress: post body HTML, REST meta fields, and taxonomy terms.

Labels such as "Learning Goals" come from this template; all other words come from the record.
"""
from __future__ import annotations

import html
import re

from . import ricos
from .schema import Activity

TEMPLATE_LABELS = ("Learning Goals", "Set Up", "Instructions", "Reflection Journal",
                   "Practice Journal", "Additional Resources", "Download the activity PDF")


def _esc(t: str) -> str:
    return html.escape(t)


def body_html(a: Activity, media: dict | None = None) -> str:
    """Post body. `media` maps 'pdf', 'image', and 'inline:<source url>' to re-hosted files."""
    media = media or {}
    inline = {k[len("inline:"):]: v["url"] for k, v in media.items() if k.startswith("inline:") and v.get("url")}
    pdf_url = (media.get("pdf") or {}).get("url") or a.pdf_url
    parts = [f"<p>{_esc(a.description)}</p>"] if a.description else []
    if a.goals:
        parts.append("<h2>Learning Goals</h2>")
        parts.append("<ul>" + "".join(f"<li>{ricos._inline_html(g)}</li>" for g in a.goals) + "</ul>")
    parts.append("<h2>Instructions</h2>")
    if a.setup:
        parts.append(ricos.blocks_to_html(a.setup, media_urls=inline))
    for s in a.steps:
        parts.append(f"<h3>{_esc(s.heading)}</h3>")
        parts.append(ricos.blocks_to_html(s.blocks, heading_offset=2, media_urls=inline))
    for label, blocks in (("Reflection Journal", a.reflection_journal),
                          ("Practice Journal", a.practice_journal),
                          ("Additional Resources", a.resources)):
        if blocks:
            parts.append(f"<h2>{label}</h2>")
            parts.append(ricos.blocks_to_html(blocks, media_urls=inline))
    if pdf_url:
        parts.append(f'<p><a href="{_esc(pdf_url)}">Download the activity PDF</a></p>')
    return "\n".join(p for p in parts if p)


def meta_fields(a: Activity, media: dict | None = None) -> dict:
    """REST meta registered by the cdp-activity WordPress plugin."""
    pdf_url = ((media or {}).get("pdf") or {}).get("url") or a.pdf_url
    return {
        "cdp_activity_id": a.activity_id,
        "cdp_number": a.number,
        "cdp_duration_minutes": a.duration_minutes or 0,
        "cdp_contributor": a.contributor or "",
        "cdp_pdf_url": pdf_url or "",
        "cdp_source_url": a.source_url or "",
        "cdp_image_credit": a.image_credit or "",
    }


def taxonomy_terms(a: Activity) -> dict[str, list[str]]:
    return {
        # Term names use plain spaces: Wix titles can contain non-breaking spaces.
        "cdp_module": [" ".join(f"Module {a.module_number}: {a.module_title}".split())] if a.module_number else [],
        "cdp_level": [a.level] if a.level else [],
        "cdp_format": list(a.tags),
    }


def html_to_text(h: str) -> str:
    """Visible text of rendered HTML, one line per block element."""
    h = re.sub(r"<(script|style|iframe)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"</(p|li|h[1-6]|ul|ol|div)>", "\n", h, flags=re.I)
    h = re.sub(r"<[^>]+>", "", h)
    return html.unescape(h)
