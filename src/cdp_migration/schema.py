"""Activity data model shared by every tool.

A Block is a small dict that keeps the structure of the source rich text:
  {"type": "heading", "level": 2, "text": "..."}
  {"type": "paragraph", "text": "..."}            # inline links are kept as [text](url)
  {"type": "list", "ordered": False, "items": ["...", "..."]}
  {"type": "html", "html": "<iframe ...>"}       # embedded content, always flagged for review
  {"type": "image", "src": "https://...", "alt": "..."}
  {"type": "callout", "text": "...", "html": "<p>...</p>", "source_html": "..."}  # a Wix HTML text box

Verbatim fields hold the activity wording and must never be rewritten.
Derived fields are produced by software (tags, summaries) and are always reviewed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

Block = dict[str, Any]

LEVELS = ("Beginner", "Advanced")
# Icon titles seen on the live Toolkit (October 2026). Unknown icons are kept and flagged.
KNOWN_TAGS = (
    "Asynchronous", "Connection", "Emotion", "Facilitation", "Listening",
    "Playful", "Professional", "Tactile", "Warm-up",
)

VERBATIM_TEXT_FIELDS = ("title", "description", "goals")
VERBATIM_BLOCK_FIELDS = ("setup", "reflection_journal", "practice_journal", "resources")


@dataclass
class Step:
    number: int
    title: str
    minutes: int | None
    optional: bool
    heading: str            # the source heading, verbatim
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Activity:
    activity_id: str                     # stable key: slug of the Wix URL
    number: str                          # "1.3"
    title: str
    module_number: int
    module_title: str
    description: str
    duration_minutes: int | None
    level: str | None
    tags: list[str]
    goals: list[str]
    setup: list[Block]
    steps: list[Step]
    reflection_journal: list[Block]
    practice_journal: list[Block]
    resources: list[Block]
    contributor: str | None = None
    pdf_url: str | None = None
    image_url: str | None = None
    image_alt: str | None = None
    image_credit: str | None = None
    tag_notes: dict[str, str] = field(default_factory=dict)
    source_url: str | None = None
    source_updated: str | None = None
    derived: dict[str, Any] = field(default_factory=dict)  # AI generated, always reviewed

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Activity":
        d = dict(d)
        d["steps"] = [s if isinstance(s, Step) else Step(**s) for s in d.get("steps", [])]
        return cls(**d)

    def content_hash(self) -> str:
        """Hash of everything except derived fields; used to prove a record is unchanged since QA."""
        d = self.to_dict()
        d.pop("derived", None)
        raw = json.dumps(d, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()


def blocks_text(blocks: list[Block]) -> str:
    """Plain text of a block list, one line per paragraph or list item."""
    out: list[str] = []
    for b in blocks:
        t = b.get("type")
        if t in ("heading", "paragraph"):
            out.append(b.get("text", ""))
        elif t == "list":
            out.extend(b.get("items", []))
        elif t == "callout":
            out.extend(b.get("text", "").splitlines())
    return "\n".join(s for s in out if s)


def activity_text_fields(a: Activity) -> dict[str, str]:
    """Every verbatim field of an activity as plain text, keyed by field path."""
    fields = {
        "title": a.title,
        "description": a.description,
        "goals": "\n".join(a.goals),
        "setup": blocks_text(a.setup),
        "reflection_journal": blocks_text(a.reflection_journal),
        "practice_journal": blocks_text(a.practice_journal),
        "resources": blocks_text(a.resources),
    }
    for s in a.steps:
        fields[f"step_{s.number}.heading"] = s.heading
        fields[f"step_{s.number}.body"] = blocks_text(s.blocks)
    return fields
