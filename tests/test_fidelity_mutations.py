"""Every change below must make check_fidelity fail. Each one slipped past an earlier version."""
import copy

import pytest

from cdp_migration import synthetic, tools as T
from cdp_migration.evaluation import make_ctx


def _rich_record():
    rec = copy.deepcopy(synthetic.make_toolkit(seed=5)[0])
    nodes = rec["activityInstructions"]["nodes"]
    nodes.append(synthetic._para(synthetic._text("Open the "), synthetic._text("guide", link="https://www.collaborativediscussionproject.com/guide"), synthetic._text(".")))
    nodes.append({"type": "HTML", "id": "x", "nodes": [], "htmlData": {"html": '<iframe src="https://docs.google.com/presentation/d/a/embed"></iframe>'}})
    nodes.append(synthetic._list(["Bring paper.", "Bring pens."]))
    rec["activityGoals"]["nodes"][1] = synthetic._list(["First goal here.", "Second goal here."])
    rec["activityReflectionJournal"]["nodes"] = [synthetic._heading("Reflection Journal", 2),
                                                 synthetic._para(synthetic._text("Prompt A?")),
                                                 synthetic._para(synthetic._text("Prompt B?"))]
    return rec


def _ctx_with_activity():
    rec = _rich_record()
    ctx = make_ctx([rec])
    aid = rec["urlNoSpaceText"]
    T.call(ctx, "crawl_toolkit", {})
    T.call(ctx, "fetch_page", {"activity_id": aid})
    T.call(ctx, "extract_activity", {"activity_id": aid})
    assert T.call(ctx, "check_fidelity", {"activity_id": aid})["ok"] is True
    return ctx, aid


def _last_step_with(a, kind):
    return next(s for s in reversed(a.steps) if any(b["type"] == kind for b in s.blocks))


def swap_goals(a): a.goals.reverse()
def swap_step_bodies(a): a.steps[0].blocks, a.steps[1].blocks = a.steps[1].blocks, a.steps[0].blocks
def move_setup_to_last(a): a.steps[-1].blocks.append(a.setup.pop())
def reverse_journal(a): a.reflection_journal.reverse()
def change_link(a):
    s = a.steps[-1]
    for b in s.blocks:
        if b["type"] == "paragraph" and "](" in b["text"]:
            b["text"] = b["text"].replace("/guide", "/other")
def replace_embed(a):
    for b in _last_step_with(a, "html").blocks:
        if b["type"] == "html":
            b["html"] = "<script>alert(1)</script>"
def add_embed(a): a.steps[0].blocks.append({"type": "html", "html": "<iframe src='https://x.test'></iframe>"})
def flip_level(a): a.level = "Advanced" if a.level == "Beginner" else "Beginner"
def replace_tags(a): a.tags = ["Playful"] if a.tags != ["Playful"] else ["Tactile"]
def change_module_title(a): a.module_title = "Other Module"
def change_contributor(a): a.contributor = "Someone Else"
def change_pdf(a): a.pdf_url = "https://evil.example.com/x.pdf"
def change_image(a): a.image_url = "https://evil.example.com/x.jpg"
def flip_optional(a): a.steps[0].optional = not a.steps[0].optional
def change_step_title(a): a.steps[0].title = "Different title"
def duplicate_sentence(a): a.steps[0].blocks.append(dict(a.steps[1].blocks[0]))
def add_not(a): a.steps[0].blocks.append({"type": "paragraph", "text": "not"})
def switch_list_kind(a):
    for b in _last_step_with(a, "list").blocks:
        if b["type"] == "list":
            b["ordered"] = not b["ordered"]


@pytest.mark.parametrize("mutate", [
    swap_goals, swap_step_bodies, move_setup_to_last, reverse_journal, change_link, replace_embed,
    add_embed, flip_level, replace_tags, change_module_title, change_contributor, change_pdf, change_image,
    flip_optional, change_step_title, duplicate_sentence, add_not, switch_list_kind])
def test_mutation_is_caught(mutate):
    ctx, aid = _ctx_with_activity()
    a = ctx.state.activity(aid)
    mutate(a)
    ctx.state.get(aid).activity = a.to_dict()
    out = T.call(ctx, "check_fidelity", {"activity_id": aid})
    assert out["ok"] is False, (mutate.__name__, out)


def test_realistic_variants_are_not_blocked():
    rec = _rich_record()
    rec["activityPracticeJournal"]["nodes"] = [synthetic._para(synthetic._text("Practice Journal:")),
                                               synthetic._para(synthetic._text("Try it at work."))]
    rec["activityGoals"]["nodes"].append(synthetic._heading("By the end, participants will:", 3))
    rec["activityGoals"]["nodes"].append(synthetic._list(["Name one habit."]))
    rec["activityInstructions"]["nodes"].append(synthetic._para(synthetic._text("Use [brackets] and a back\\slash as written.")))
    ctx = make_ctx([rec])
    aid = rec["urlNoSpaceText"]
    T.call(ctx, "crawl_toolkit", {})
    for step in ("fetch_page", "extract_activity", "validate_activity"):
        T.call(ctx, step, {"activity_id": aid})
    out = T.call(ctx, "check_fidelity", {"activity_id": aid})
    assert out["ok"] is True, out
    from cdp_migration.render import body_html
    html = body_html(ctx.state.activity(aid))
    assert "Use [brackets] and a back\\slash as written." in html and "Practice Journal:" not in html


def test_image_alt_change_is_caught():
    rec = _rich_record()
    rec["activityInstructions"]["nodes"].append({"type": "IMAGE", "id": "i", "nodes": [], "imageData": {
        "image": {"src": {"id": "b09383_x~mv2.png"}}, "altText": "Group diagram"}})
    ctx = make_ctx([rec])
    aid = rec["urlNoSpaceText"]
    T.call(ctx, "crawl_toolkit", {})
    for step in ("fetch_page", "extract_activity"):
        T.call(ctx, step, {"activity_id": aid})
    assert T.call(ctx, "check_fidelity", {"activity_id": aid})["ok"] is True
    a = ctx.state.activity(aid)
    for s in a.steps:
        for b in s.blocks:
            if b["type"] == "image":
                b["alt"] = "Something else"
    ctx.state.get(aid).activity = a.to_dict()
    assert T.call(ctx, "check_fidelity", {"activity_id": aid})["ok"] is False


# The structure of the 58 HTML text boxes on the live Toolkit (November 2026), with invented wording.
CARD = ('<!DOCTYPE html>\n<html>\n<head>\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<style>\n* {\n  box-sizing: border-box;\n}\nbody {\n  font-family: Calibri, Arial, sans-serif;\n  color: #150c3f;\n}\n'
        '.column {\n  float: left;\n  width: 100%;\n}\n</style>\n</head>\n<body>\n<div>\n  <div class="column">\n'
        '    <div class="card">\n      <p><span style="font-weight:bold;">Online Adaptation:</span> Ask people to add notes '
        'to a shared board &amp; group them.&nbsp;<a href="https://docs.google.com/presentation/d/abc/edit?usp=sharing" '
        'target="_blank"><span style="color: #536afd;">Click here to view a sample board.</span></a></p>\n    </div>\n'
        '  </div>\n</div>\n</body>\n</html>\n')


def _card_ctx():
    rec = _rich_record()
    nodes = rec["activityInstructions"]["nodes"]
    nodes[:] = [n for n in nodes if n.get("type") != "HTML"]
    nodes.append({"type": "HTML", "id": "c", "nodes": [], "htmlData": {"html": CARD, "source": "HTML"}})
    rec["activityPageModuleTitle"] = "Critical\xa0Collaboration"
    ctx = make_ctx([rec])
    aid = rec["urlNoSpaceText"]
    T.call(ctx, "crawl_toolkit", {})
    for step in ("fetch_page", "extract_activity"):
        T.call(ctx, step, {"activity_id": aid})
    return ctx, aid


def test_text_box_becomes_a_checked_callout():
    from cdp_migration.render import body_html, taxonomy_terms

    ctx, aid = _card_ctx()
    assert T.call(ctx, "validate_activity", {"activity_id": aid})["ok"] is True
    assert T.call(ctx, "check_fidelity", {"activity_id": aid})["ok"] is True
    a = ctx.state.activity(aid)
    html = body_html(a)
    assert '<div class="cdp-callout"><p><strong>Online Adaptation:</strong> Ask people' in html
    assert '<a href="https://docs.google.com/presentation/d/abc/edit?usp=sharing">Click here' in html
    assert "<style" not in html and "font-family" not in html
    assert taxonomy_terms(a)["cdp_module"] == ["Module 1: Critical Collaboration"]


def test_text_box_wording_change_is_caught():
    ctx, aid = _card_ctx()
    a = ctx.state.activity(aid)
    for s in a.steps:
        for b in s.blocks:
            if b["type"] == "callout":
                b["text"] = b["text"].replace("Ask people", "Tell people")
    ctx.state.get(aid).activity = a.to_dict()
    assert T.call(ctx, "check_fidelity", {"activity_id": aid})["ok"] is False


@pytest.mark.parametrize("edit", [
    lambda b: b.update(html=b["html"].replace("https://docs.google.com", "https://evil.example")),
    lambda b: b.update(html=b["html"] + "<script>alert(1)</script>"),
    lambda b: b.update(text=b["text"].replace("https://docs.google.com", "https://evil.example")),
])
def test_callout_html_and_links_cannot_be_edited(edit):
    ctx, aid = _card_ctx()
    a = ctx.state.activity(aid)
    for s in a.steps:
        for b in s.blocks:
            if b["type"] == "callout":
                edit(b)
    ctx.state.get(aid).activity = a.to_dict()
    assert T.call(ctx, "check_fidelity", {"activity_id": aid})["ok"] is False


def test_unsafe_link_schemes_are_not_copied():
    from cdp_migration import ricos

    for href in ("javascript:alert(1)", "JaVaScRiPt:x", "data:text/html,x", "java\tscript:x"):
        assert ricos.html_card(f'<p><a href="{href}">x</a></p>') is None
    card = ricos.html_card('<p>A <a href="https://x.org/a"><span>Click</span> <span>here</span></a>\n now.</p><!-- a > b -->')
    assert card["html"] == '<p>A <a href="https://x.org/a">Click here</a> now.</p>'
