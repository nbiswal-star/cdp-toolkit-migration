"""Synthetic Toolkit data with the same structure as the live Wix pages.

The node shapes, field names, heading conventions ("Step Two: Title (10 min)"), icon
vocabulary, and module sizes match what the live site served in October 2026. All wording
is invented, so tests and evaluation never copy IF content.
"""
from __future__ import annotations

import base64
import hashlib
import json
import random
from typing import Any

from .wix import SITE

MODULES = {
    1: ("Introduction to Collaborative Discussion", 10),
    2: ("Creative Collaboration", 9),
    3: ("Critical Collaboration", 10),
    4: ("Culturally Responsive Collaboration", 9),
    5: ("Civic Collaboration", 8),
}
TAG_POOL = ["Asynchronous", "Connection", "Emotion", "Facilitation", "Listening",
            "Playful", "Professional", "Tactile", "Warm-up"]
NUM_WORDS = ["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight"]
VERBS = ["Map", "Share", "Rank", "Sketch", "Compare", "Reframe", "Test", "Summarize", "Explore", "Name"]
GERUNDS = ["Mapping", "Sharing", "Ranking", "Sketching", "Comparing", "Reframing", "Testing",
           "Summarizing", "Exploring", "Naming"]
OBJECTS = ["Shared Assumptions", "Group Strengths", "Open Questions", "Listening Habits",
           "Turning Points", "Common Ground", "Hidden Tensions", "Next Steps", "Story Threads"]
SENTENCES = [
    "Invite each participant to write down two ideas before anyone speaks.",
    "Ask small groups to compare their notes and look for patterns.",
    "Remind the group that every contribution is welcome at this stage.",
    "Give each group a large sheet of paper and three colored markers.",
    "Encourage participants to build on one another's ideas rather than debate them.",
    "Close the round by asking one volunteer from each group to report back.",
    "Keep time visible so groups can pace their discussion.",
    "Note recurring themes on a shared board for everyone to see.",
]
PROMPTS = [
    "What surprised you most during this activity?",
    "Which idea from another person changed your thinking?",
    "How might you use this approach in your next group meeting?",
    "When did the conversation feel most productive, and why?",
]
TINY_JPEG = base64.b64decode("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDPooor6w1P/9k=")


def tiny_pdf(label: str) -> bytes:
    """A small but valid one-page PDF, so WordPress accepts the upload."""
    text = label.replace("(", "").replace(")", "")[:60]
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


COMMENTERS = ["Riley Fenwick", "Jordan Okafor", "Sam Petrakis"]
ICON_NOTES = {"Beginner": "This activity can be completed by any discussion group.",
              "Advanced": "This activity is best for groups with some practice."}


def _text(t: str, link: str | None = None) -> dict[str, Any]:
    deco = [{"type": "LINK", "linkData": {"link": {"url": link, "target": "BLANK"}}}] if link else []
    return {"type": "TEXT", "id": "", "nodes": [], "textData": {"text": t, "decorations": deco}}


def _para(*texts: dict[str, Any]) -> dict[str, Any]:
    return {"type": "PARAGRAPH", "id": "p", "nodes": list(texts),
            "paragraphData": {"textStyle": {"textAlignment": "AUTO"}}}


def _empty() -> dict[str, Any]:
    return {"type": "PARAGRAPH", "id": "e", "nodes": [], "paragraphData": {}}


def _heading(t: str, level: int = 1) -> dict[str, Any]:
    return {"type": "HEADING", "id": "h", "nodes": [_text(t)], "headingData": {"level": level}}


def _list(items: list[str], ordered: bool = False) -> dict[str, Any]:
    kind = "ORDERED_LIST" if ordered else "BULLETED_LIST"
    return {"type": kind, "id": "l", "nodes": [
        {"type": "LIST_ITEM", "id": "li", "nodes": [_para(_text(i))]} for i in items]}


def _doc(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {"nodes": nodes, "metadata": {"version": 1}, "documentStyle": {}}


def make_record(module: int, index: int, rng: random.Random) -> dict[str, Any]:
    number = f"{module}.{index}"
    title = f"{rng.choice(GERUNDS)} {rng.choice(OBJECTS)}"
    slug = (number.replace(".", "") + title).lower().replace(" ", "").replace("-", "")
    n_steps = rng.randint(3, 8)
    total = rng.choice([35, 40, 45, 50, 55, 60, 65])   # live range, October 2026
    n_steps = min(n_steps, total // 5)
    minutes = [5] * n_steps                            # step times add up to the activity time
    for _ in range((total - 5 * n_steps) // 5):
        minutes[rng.randrange(n_steps)] += 5
    instr = [_heading("Instructions", 2), _empty(), _heading("Set Up: Prepare for the Activity"),
             _para(_text(rng.choice(SENTENCES))), _para(_text("Begin by introducing the learning goals of this activity."))]
    for s in range(1, n_steps + 1):
        optional = s == n_steps - 1 and rng.random() < 0.2
        name = f"{rng.choice(VERBS)} {rng.choice(OBJECTS)}"
        if s == n_steps:
            name = "Debrief as a Full Group"
        head = f"Step {NUM_WORDS[s]}{' (optional)' if optional else ''}: {name} ({minutes[s-1]} min)"
        instr.append(_heading(head))
        instr.append(_para(_text(rng.choice(SENTENCES))))
        if rng.random() < 0.5:
            instr.append(_list(rng.sample(PROMPTS, 2), ordered=rng.random() < 0.2))
        if rng.random() < 0.15:
            instr.append({"type": "HTML", "id": "x", "nodes": [], "htmlData": {
                "html": '<iframe src="https://docs.google.com/presentation/d/example/embed"></iframe>', "source": "HTML"}})
        if rng.random() < 0.2:
            instr.append(_para(_text("See the "), _text("worksheet", link=f"{SITE}/activity-materials"), _text(" for details.")))
    level = "Advanced" if rng.random() < 0.2 else "Beginner"
    tags = rng.sample(TAG_POOL, rng.randint(1, 3))
    icons = [{"title": t, "alt": t, "type": "image",
              "description": ICON_NOTES.get(t, f"This activity supports {t.lower()} learning."),
              "src": f"wix:image://v1/b09383_{t.lower()}~mv2.png/{t}.png"} for t in [level] + tags]
    rid = f"{module:02d}{index:02d}-synthetic"
    return {
        "_id": rid,
        "title": f"{number} \n{title}",
        "module": f"Module {module}",
        "activityPageModuleTitle": MODULES[module][0],
        "activityContributor": "Submitted By Toolkit Author",
        "activityDescription": f"This activity helps groups practice {title.lower()} together.",
        "activityTime": total,
        "activityIcons": icons,
        "activityGoals": _doc([_heading("Learning Goals", 2), _list([
            f"Practice {title.lower()} in a supportive setting.", rng.choice(SENTENCES)])]),
        "activityInstructions": _doc(instr),
        "activityReflectionJournal": _doc([_heading("Reflection Journal", 2), _empty(),
                                            _para(_text(rng.choice(PROMPTS))), _para(_text(rng.choice(PROMPTS)))]),
        "activityPracticeJournal": _doc([_heading("Practice Journal", 2), _para(_text(rng.choice(SENTENCES)))]),
        "activityResources": _doc([_heading("Additional Resources", 2),
                                   _list([f"Reading list for module {module}"])]),
        "activityPdf": f"wix:document://v1/ugd/b09383_{rid.replace('-', '')}.pdf/{number}.pdf",
        "activityImage": f"wix:image://v1/b09383_{rid.replace('-', '')}~mv2.jpg/photo.jpg#originWidth=640",
        "activityImageAltText": "Abstract illustration",
        "activityImageCredit": "Photo by Example on Unsplash",
        "urlNoSpaceText": slug,
        "link-items-1-title": f"/items-1/{slug}",
        "_updatedDate": {"$date": "2026-09-01T00:00:00.000Z"},
    }


def make_toolkit(seed: int = 7) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    return [make_record(m, i, rng) for m, (_, n) in MODULES.items() for i in range(1, n + 1)]


def page_html(rec: dict[str, Any], with_comments: bool = True) -> str:
    cols: dict[str, Any] = {"Items1": {rec["_id"]: rec}}
    if with_comments:
        cols["comments"] = {f"c{i}": {"name": n, "comment": "Helpful activity, thank you."}
                            for i, n in enumerate(COMMENTERS)}
    warm = {"appsWarmupData": {"dataBinding": {"dataStore": {"recordsByCollectionId": cols}}}}
    return ("<html><head><title>Toolkit</title></head><body><main>Rendered page</main>"
            f'<script type="application/json" id="wix-warmup-data">{json.dumps(warm)}</script>'
            "</body></html>")


def module_page_html(records: list[dict[str, Any]], module: int) -> str:
    links = "".join(f'<a href="{SITE}{r["link-items-1-title"]}">Go to Activity</a>'
                    for r in records if r["module"] == f"Module {module}")
    return f"<html><body>{links}</body></html>"


class FakeSite:
    """In-memory HTTP fetcher for the synthetic Toolkit; used by tests and offline evaluation."""

    def __init__(self, records: list[dict[str, Any]] | None = None):
        self.records = records or make_toolkit()
        self.requests: list[str] = []

    def get(self, url: str) -> tuple[int, str, bytes]:
        self.requests.append(url)
        path = url.replace(SITE, "")
        if path.startswith("/activities/module-"):
            return 200, "text/html", module_page_html(self.records, int(path.rsplit("-", 1)[1])).encode()
        for r in self.records:
            if path == r["link-items-1-title"]:
                return 200, "text/html", page_html(r).encode()
        if path.startswith("/_files/ugd/"):
            return 200, "application/pdf", tiny_pdf(path)
        if url.startswith("https://static.wixstatic.com/"):
            return 200, "image/jpeg", TINY_JPEG + hashlib.sha256(url.encode()).digest()
        if path == "/activity-materials" or url.startswith("https://docs.google.com/"):
            return 200, "text/html", b"<html>ok</html>"
        return 404, "text/html", b"not found"
