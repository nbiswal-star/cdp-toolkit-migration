import copy

from cdp_migration import synthetic, tools as T
from cdp_migration.adapters import PublishBlocked
from cdp_migration.evaluation import CASES, CONFIGS, make_ctx, run_case
from cdp_migration.guardrails import Guardrails
from cdp_migration.http import DomainNotAllowed
from cdp_migration.pipeline import approve, migrate


def _prep(ctx, aid):
    T.call(ctx, "crawl_toolkit", {})
    for step in ("fetch_page", "extract_activity", "validate_activity", "check_fidelity", "scan_pii"):
        T.call(ctx, step, {"activity_id": aid})


def test_every_tool_has_llm_docstring_and_schema():
    assert len(T.REGISTRY) >= 5
    for name in T.REGISTRY:
        s = T.tool_schema(T.REGISTRY[name])
        assert "Args:" in s["description"] and "Returns:" in s["description"], name
        assert "ctx" not in s["input_schema"]["properties"]
    assert T.tool_schema(T.REGISTRY["crawl_toolkit"])["input_schema"]["properties"]["modules"]["type"] == "array"


def test_crawl_finds_all_46(ctx):
    out = T.call(ctx, "crawl_toolkit", {})
    assert out["count"] == 46 and not out["warnings"]


def test_clean_pipeline_drafts_everything_once(ctx):
    res = migrate(ctx)
    assert len(res.drafted) == 46 and not res.review
    assert all(p["status"] == "draft" for p in ctx.adapter.posts.values())
    n_media = len(ctx.adapter.media)
    res2 = migrate(ctx)  # re-run: same posts, no new media
    assert len(res2.drafted) == 46 and len(ctx.adapter.posts) == 46 and len(ctx.adapter.media) == n_media
    assert (ctx.out_dir / "redirects.csv").read_text().count("\n") == 47


def test_each_planted_case_blocked_with_guardrails_and_through_without():
    for case in CASES:
        assert run_case(case, Guardrails())["drafted"] is False, case.name
        assert run_case(case, Guardrails.off())["drafted"] is True, case.name


def test_configs_cover_each_layer():
    assert set(CONFIGS) >= {"all guardrails on", "all guardrails off"}


def test_create_draft_refuses_without_checks(ctx, records):
    aid = records[0]["urlNoSpaceText"]
    T.call(ctx, "crawl_toolkit", {})
    T.call(ctx, "fetch_page", {"activity_id": aid})
    T.call(ctx, "extract_activity", {"activity_id": aid})
    out = T.call(ctx, "create_draft", {"activity_id": aid})
    assert "blocked" in out["error"]


def test_human_approval_unblocks_exact_version(records, tmp_path):
    rec = copy.deepcopy(records[0])
    rec["activityDescription"] += " Contact me at a.person@example.org."
    ctx = make_ctx([rec], out_dir=tmp_path)
    aid = rec["urlNoSpaceText"]
    res = migrate(ctx)
    assert aid in res.review and not ctx.adapter.posts
    approve(ctx, aid)
    res = migrate(ctx)
    assert aid in res.drafted and ctx.adapter.posts[aid]["status"] == "draft"


def test_retry_limit(ctx):
    for _ in range(3):
        assert "error" in T.call(ctx, "fetch_page", {"activity_id": "doesnotexist"})
    assert "retry limit" in T.call(ctx, "fetch_page", {"activity_id": "doesnotexist"})["error"]


def test_adapter_refuses_publish(ctx, records):
    from cdp_migration.wix import record_to_activity

    try:
        ctx.adapter.upsert_draft(record_to_activity(records[0]), {}, status="publish")
        raise AssertionError("publish was allowed")
    except PublishBlocked:
        pass


def test_fetcher_allow_list():
    ctx = make_ctx(synthetic.make_toolkit(1)[:1])
    try:
        ctx.fetcher.get("https://evil.example.com/x")
        raise AssertionError("allow list not enforced")
    except DomainNotAllowed:
        pass


def test_source_change_resets_qa(records, tmp_path):
    ctx = make_ctx([records[0]], out_dir=tmp_path)
    aid = records[0]["urlNoSpaceText"]
    _prep(ctx, aid)
    assert ctx.state.get(aid).qa_hash
    records[0]["activityDescription"] += " Edited."
    out = T.call(ctx, "fetch_page", {"activity_id": aid})
    assert out["source_changed"] and ctx.state.get(aid).qa_hash is None


def test_broken_link_reported(records, tmp_path):
    rec = copy.deepcopy(records[0])
    rec["activityResources"]["nodes"].append(
        synthetic._para(synthetic._text("gone", link=synthetic.SITE + "/missing-page")))
    ctx = make_ctx([rec], out_dir=tmp_path)
    res = migrate(ctx)
    assert res.broken_links[rec["urlNoSpaceText"]][0]["status"] == 404


def test_shared_image_attached_to_every_activity(records, tmp_path):
    recs = copy.deepcopy(records[:2])
    recs[1]["activityImage"] = recs[0]["activityImage"]
    ctx = make_ctx(recs, out_dir=tmp_path)
    migrate(ctx)
    imgs = [p["media"].get("image", {}).get("id") for p in ctx.adapter.posts.values()]
    assert imgs[0] and imgs[0] == imgs[1] and len(ctx.adapter.media) == 3
