"""Integration test against a real WordPress with the wordpress/cdp-activity plugin active.

Skipped unless these are set (see wordpress/README.md for a local site):
  CDP_WP_URL, CDP_WP_USER, CDP_WP_APP_PASSWORD          (a user with the CDP Drafter role)
  CDP_WP_ADMIN_USER, CDP_WP_ADMIN_APP_PASSWORD          (optional: tests the published-post guard)
"""
import copy
import os
import uuid

import pytest
import requests

from cdp_migration import synthetic
from cdp_migration.adapters import WordPressAdapter
from cdp_migration.evaluation import make_ctx
from cdp_migration.pipeline import migrate

URL = os.environ.get("CDP_WP_URL")
pytestmark = pytest.mark.skipif(not URL, reason="CDP_WP_URL not set")


@pytest.fixture
def wp_records():
    recs = synthetic.make_toolkit(seed=21)[:3]
    tag = uuid.uuid4().hex[:6]
    for r in recs:  # unique ids so repeated runs do not collide
        r["urlNoSpaceText"] += tag
        r["link-items-1-title"] += tag
    return recs


def _drafter():
    return WordPressAdapter(URL, os.environ["CDP_WP_USER"], os.environ["CDP_WP_APP_PASSWORD"])


def test_drafts_created_idempotently(wp_records, tmp_path):
    ctx = make_ctx(wp_records, adapter=_drafter(), out_dir=tmp_path)
    res = migrate(ctx)
    assert len(res.drafted) == 3, res.review
    ids = {aid: ctx.state.get(aid).post_id for aid in res.drafted}
    auth = (os.environ["CDP_WP_USER"], os.environ["CDP_WP_APP_PASSWORD"])
    for aid, pid in ids.items():
        post = requests.get(f"{URL}/wp-json/wp/v2/cdp-activities/{pid}", params={"context": "edit"}, auth=auth).json()
        assert post["status"] == "draft"
        assert post["meta"]["cdp_activity_id"] == aid
        assert post["cdp_level"] and post["cdp_module"]
        assert post["featured_media"]
    res2 = migrate(ctx)
    assert {aid: ctx.state.get(aid).post_id for aid in res2.drafted} == ids


GOOGLE_EMBED = ('<iframe src="https://docs.google.com/presentation/d/e/2PACX-1/embed?start=false&loop=false&delayms=3000" '
                'frameborder="0" width="960" height="569" allowfullscreen="true" mozallowfullscreen="true" '
                'webkitallowfullscreen="true"></iframe>')


def test_embeds_kept_for_allowed_hosts_and_flagged_otherwise(wp_records, tmp_path):
    good, bad = (copy.deepcopy(r) for r in wp_records[:2])
    for rec, html in ((good, GOOGLE_EMBED), (bad, '<iframe src="https://evil.example.com/e"></iframe>')):
        rec["activityInstructions"]["nodes"].append(
            {"type": "HTML", "id": "x", "nodes": [], "htmlData": {"html": html}})
    ctx = make_ctx([good, bad], adapter=_drafter(), out_dir=tmp_path)
    res = migrate(ctx)
    assert good["urlNoSpaceText"] in res.drafted, res.review
    assert "validate_activity failed" in res.review[bad["urlNoSpaceText"]]
    assert "not on the approved list" in str(ctx.state.get(bad["urlNoSpaceText"]).qa["validate"]["errors"])


@pytest.mark.parametrize("html", [
    '<iframe src="https://evil.example/x"> </iframe>',
    '<iframe data-src="https://www.youtube.com/embed/a" src="https://evil.example/x"></iframe>',
    '<iframe src="https://evil.example/x">fallback\n</iframe>',
    '<iframe src="https://evil.example/x">',
])
def test_plugin_removes_iframes_from_other_hosts(html):
    auth = (os.environ["CDP_WP_USER"], os.environ["CDP_WP_APP_PASSWORD"])
    r = requests.post(f"{URL}/wp-json/wp/v2/cdp-activities", auth=auth,
                      json={"title": "embed probe", "status": "draft", "content": f"<p>x</p>{html}"})
    assert r.status_code == 201, r.text
    raw = requests.get(f"{URL}/wp-json/wp/v2/cdp-activities/{r.json()['id']}", params={"context": "edit"},
                       auth=auth).json()["content"]["raw"]
    assert "evil.example" not in raw


def test_unknown_tag_needs_an_administrator(wp_records, tmp_path):
    rec = copy.deepcopy(wp_records[0])
    rec["activityIcons"].append({"title": "Brand New Tag", "description": "x"})
    ctx = make_ctx([rec], adapter=_drafter(), out_dir=tmp_path)
    res = migrate(ctx)
    assert "may not create it" in res.review[rec["urlNoSpaceText"]]


def test_drafter_cannot_publish(wp_records, tmp_path):
    ctx = make_ctx(wp_records[:1], adapter=_drafter(), out_dir=tmp_path)
    migrate(ctx)
    pid = ctx.state.get(wp_records[0]["urlNoSpaceText"]).post_id
    r = requests.post(f"{URL}/wp-json/wp/v2/cdp-activities/{pid}", json={"status": "publish"},
                      auth=(os.environ["CDP_WP_USER"], os.environ["CDP_WP_APP_PASSWORD"]))
    assert r.status_code in (401, 403), r.text
    unsafe = WordPressAdapter(URL, os.environ["CDP_WP_USER"], os.environ["CDP_WP_APP_PASSWORD"], allow_publish=True)
    a = ctx.state.activity(wp_records[0]["urlNoSpaceText"])
    with pytest.raises(RuntimeError):
        unsafe.upsert_draft(a, {}, status="publish")  # WordPress itself refuses, even if our code allowed it


@pytest.mark.skipif(not os.environ.get("CDP_WP_ADMIN_APP_PASSWORD"), reason="admin credentials not set")
def test_published_post_is_never_overwritten(wp_records, tmp_path):
    ctx = make_ctx(wp_records[:1], adapter=_drafter(), out_dir=tmp_path)
    migrate(ctx)
    aid = wp_records[0]["urlNoSpaceText"]
    pid = ctx.state.get(aid).post_id
    admin = (os.environ.get("CDP_WP_ADMIN_USER", "admin"), os.environ["CDP_WP_ADMIN_APP_PASSWORD"])
    assert requests.post(f"{URL}/wp-json/wp/v2/cdp-activities/{pid}", json={"status": "publish"}, auth=admin).ok
    res = migrate(ctx)
    assert aid in res.review and "refusing to overwrite" in res.review[aid]


@pytest.mark.skipif(not os.environ.get("CDP_WP_ADMIN_APP_PASSWORD"), reason="admin credentials not set")
def test_redirects_use_published_permalinks(wp_records, tmp_path):
    from cdp_migration.cli import main

    state = tmp_path / "state.json"
    ctx = make_ctx(wp_records[:2], adapter=_drafter(), out_dir=tmp_path)
    ctx.state.path = state
    migrate(ctx)
    ctx.state.save()
    pid = ctx.state.get(wp_records[0]["urlNoSpaceText"]).post_id
    admin = (os.environ.get("CDP_WP_ADMIN_USER", "admin"), os.environ["CDP_WP_ADMIN_APP_PASSWORD"])
    assert requests.post(f"{URL}/wp-json/wp/v2/cdp-activities/{pid}", json={"status": "publish"}, auth=admin).ok
    main(["--state", str(state), "--out", str(tmp_path), "--target", "wordpress", "redirects"])
    rows = (tmp_path / "redirects.csv").read_text().splitlines()
    assert len(rows) == 2 and rows[1].startswith(f"/items-1/{wp_records[0]['urlNoSpaceText']},/")


def test_text_box_callout_survives_wordpress(wp_records, tmp_path):
    from test_fidelity_mutations import CARD

    rec = copy.deepcopy(wp_records[0])
    rec["activityInstructions"]["nodes"].append({"type": "HTML", "id": "c", "nodes": [], "htmlData": {"html": CARD}})
    rec["activityPageModuleTitle"] = rec["activityPageModuleTitle"].replace(" ", "\xa0", 1)
    ctx = make_ctx([rec], adapter=_drafter(), out_dir=tmp_path)
    res = migrate(ctx)
    assert rec["urlNoSpaceText"] in res.drafted, res.review
