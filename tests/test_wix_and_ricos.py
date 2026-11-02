import pytest

from cdp_migration import ricos, synthetic, wix


def test_step_heading_variants():
    assert wix.parse_step_heading("Step Two: Prioritize Attributes (10 min)") == (2, "Prioritize Attributes", 10, False)
    assert wix.parse_step_heading("Step Four (optional): Rank Top 5 (15 min)") == (4, "Rank Top 5", 15, True)
    assert wix.parse_step_heading("Step Eight: Debrief as Full Group (10 mins)")[0] == 8
    assert wix.parse_step_heading("Step Four: Showcase Designs (If the activity runs long)")[2] is None
    assert wix.parse_step_heading("Set Up: Prepare for the Activity") is None


def test_warmup_extraction_and_comments(records):
    html = synthetic.page_html(records[0])
    rec = wix.activity_record(html)
    assert rec["_id"] == records[0]["_id"]
    assert wix.commenter_names(html) == set(synthetic.COMMENTERS)


def test_page_without_record_raises():
    with pytest.raises(wix.WixPageError):
        wix.activity_record("<html><body>no data</body></html>")


def test_record_to_activity_fields(records):
    rec = records[0]
    a = wix.record_to_activity(rec)
    assert a.number == "1.1" and a.module_number == 1
    assert a.title == rec["title"].split("\n", 1)[1]
    assert a.level in ("Beginner", "Advanced")
    assert a.steps and [s.number for s in a.steps] == list(range(1, len(a.steps) + 1))
    assert a.setup[0]["text"].startswith("Set Up")
    assert a.pdf_url.startswith(wix.SITE + "/_files/ugd/")
    assert a.image_url.startswith("https://static.wixstatic.com/media/")
    assert a.contributor == "Toolkit Author"
    assert all(b["text"].lower() != "reflection journal" for b in a.reflection_journal if "text" in b)


def test_ricos_links_lists_and_html():
    doc = synthetic._doc([
        synthetic._para(synthetic._text("See the "), synthetic._text("sheet", link="https://x.test/s"), synthetic._text(".")),
        synthetic._list(["one", "two"], ordered=True),
        {"type": "HTML", "nodes": [], "htmlData": {"html": '<iframe src="https://v.test/e"></iframe>'}},
        synthetic._empty(),
    ])
    blocks = ricos.to_blocks(doc)
    assert blocks[0] == {"type": "paragraph", "text": "See the [sheet](https://x.test/s)."}
    assert blocks[1] == {"type": "list", "ordered": True, "items": ["one", "two"]}
    assert blocks[2]["type"] == "html" and len(blocks) == 3
    html = ricos.blocks_to_html(blocks)
    assert '<a href="https://x.test/s">sheet</a>' in html and "<ol><li>one</li>" in html
    assert set(ricos.links_in_blocks(blocks)) == {"https://x.test/s", "https://v.test/e"}


def test_module_page_links(records):
    html = synthetic.module_page_html(records, 2)
    paths = wix.item_paths(html)
    assert len(paths) == 9 and all(p.startswith("/items-1/") for p in paths)
