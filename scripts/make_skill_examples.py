"""Regenerate the skill folder's JSON schema and worked examples (synthetic activities only)."""
from __future__ import annotations

import json
from pathlib import Path

from cdp_migration import synthetic, wix

ROOT = Path(__file__).resolve().parents[1] / "skills" / "toolkit-activity-publisher"

SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Toolkit Activity",
    "type": "object",
    "required": ["activity_id", "number", "title", "module_number", "description", "duration_minutes",
                 "level", "goals", "steps"],
    "properties": {
        "activity_id": {"type": "string", "description": "slug of the old Toolkit URL"},
        "number": {"type": "string", "pattern": r"^\d+\.\d+$"},
        "title": {"type": "string", "minLength": 1},
        "module_number": {"type": "integer", "minimum": 1, "maximum": 5},
        "module_title": {"type": "string"},
        "description": {"type": "string", "minLength": 1},
        "duration_minutes": {"type": "integer", "minimum": 5, "maximum": 240},
        "level": {"enum": ["Beginner", "Advanced"]},
        "tags": {"type": "array", "items": {"type": "string"}},
        "goals": {"type": "array", "minItems": 1, "items": {"type": "string"}},
        "setup": {"$ref": "#/$defs/blocks"},
        "steps": {"type": "array", "minItems": 2, "items": {
            "type": "object", "required": ["number", "title", "heading", "blocks"],
            "properties": {"number": {"type": "integer"}, "title": {"type": "string"},
                           "minutes": {"type": ["integer", "null"]}, "optional": {"type": "boolean"},
                           "heading": {"type": "string", "description": "source heading, verbatim"},
                           "blocks": {"$ref": "#/$defs/blocks"}}}},
        "reflection_journal": {"$ref": "#/$defs/blocks"},
        "practice_journal": {"$ref": "#/$defs/blocks"},
        "resources": {"$ref": "#/$defs/blocks"},
        "contributor": {"type": ["string", "null"]},
        "pdf_url": {"type": ["string", "null"]},
    },
    "$defs": {"blocks": {"type": "array", "items": {"type": "object", "required": ["type"], "properties": {
        "type": {"enum": ["heading", "paragraph", "list", "html", "image"]},
        "text": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}},
        "ordered": {"type": "boolean"}, "html": {"type": "string"}, "src": {"type": "string"}}}}},
}


def _section(blocks) -> str:
    out = []
    for b in blocks:
        if b["type"] == "html":
            from cdp_migration.ricos import embed_iframes
            src = next((f.get("src") for f in embed_iframes(b["html"]) if f.get("src")), "link from the source")
            out.append(f"[Embed: {src}]")
        elif b["type"] == "list":
            out.extend(f"- {i.strip()}" for i in b["items"])
        elif b["type"] in ("paragraph", "heading"):
            out.append(b["text"])
    return "\n".join(out)


def to_markdown(a) -> str:
    lines = [f"# {a.number} {a.title}", "", f"- **Module:** {a.module_number}: {a.module_title}",
             f"- **Time:** {a.duration_minutes} min", f"- **Level:** {a.level}", f"- **Tags:** {', '.join(a.tags)}",
             f"- **Submitted by:** {a.contributor}", f"- **PDF:** {a.pdf_url}", f"- **Image credit:** {a.image_credit}", "", a.description, "",
             "## Learning Goals", ""] + [f"- {g}" for g in a.goals] + ["", "## Instructions", ""]
    lines += [f"### {a.setup[0]['text']}" if a.setup else "", "", _section(a.setup[1:]), ""]
    for s in a.steps:
        lines += [f"### {s.heading}", "", _section(s.blocks), ""]
    for label, blocks in (("Reflection Journal", a.reflection_journal), ("Practice Journal", a.practice_journal),
                          ("Additional Resources", a.resources)):
        lines += [f"## {label}", "", _section(blocks), ""]
    lines += ["---", "", "**Flagged:** none", "", "**Questions for the author:** none", ""]
    return "\n".join(lines)


def main() -> None:
    (ROOT / "schema").mkdir(parents=True, exist_ok=True)
    (ROOT / "schema" / "activity.schema.json").write_text(json.dumps(SCHEMA, indent=1) + "\n")
    recs = synthetic.make_toolkit(seed=7)
    acts = [wix.record_to_activity(r) for r in recs]
    picks = {"short": min(acts, key=lambda a: len(a.steps)),
             "long": max(acts, key=lambda a: len(a.steps)),
             "with-embed": next(a for a in acts if any(b["type"] == "html" for s in a.steps for b in s.blocks))}
    (ROOT / "examples").mkdir(exist_ok=True)
    for name, a in picks.items():
        (ROOT / "examples" / f"{name}.md").write_text(
            "<!-- Synthetic example: invented wording in the real Toolkit layout. -->\n" + to_markdown(a))


if __name__ == "__main__":
    main()
