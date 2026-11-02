"""Command line: `cdp <command>`. Run `cdp -h` for the list."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import tools as T
from .adapters import FileExportAdapter, WordPressAdapter
from .guardrails import Guardrails
from .http import LinkChecker, PoliteFetcher
from .state import StateStore


def build_ctx(args) -> T.ToolContext:
    g = Guardrails()
    if args.target == "wordpress":
        missing = [v for v in ("CDP_WP_URL", "CDP_WP_USER", "CDP_WP_APP_PASSWORD") if not os.environ.get(v)]
        if missing:
            sys.exit(f"Set {', '.join(missing)} (see README, 'WordPress target').")
        adapter = WordPressAdapter(os.environ["CDP_WP_URL"], os.environ["CDP_WP_USER"],
                                   os.environ["CDP_WP_APP_PASSWORD"])
    else:
        adapter = FileExportAdapter(args.export_dir)
    from .llm import from_env

    return T.ToolContext(fetcher=PoliteFetcher(args.cache, delay=args.delay, allow=g.allow_hosts),
                         link_fetcher=LinkChecker(),
                         adapter=adapter, state=StateStore(args.state), guardrails=g,
                         llm=from_env(), out_dir=Path(args.out))


def cmd_inventory(args):
    ctx = build_ctx(args)
    print(json.dumps(T.call(ctx, "crawl_toolkit", {}), indent=1))


def cmd_migrate(args):
    from .pipeline import migrate

    ctx = build_ctx(args)
    res = migrate(ctx, only=args.only, limit=args.limit)
    if isinstance(ctx.adapter, FileExportAdapter):
        print(f"WordPress import file: {ctx.adapter.write_wxr(res.drafted)}")
    print(f"Drafted: {len(res.drafted)}   Needs review: {len(res.review)}")
    for aid, why in res.review.items():
        print(f"  review  {aid}: {why}")
    print("Run `cdp review` for details.")


def cmd_agent(args):
    from .agents.orchestrator import run_migration
    from .llm import from_env

    llm = from_env()
    if llm is None:
        sys.exit("Set ANTHROPIC_API_KEY to run the agent. `cdp migrate` runs the same tools without an LLM.")
    ctx = build_ctx(args)
    ctx.llm = llm
    rep = run_migration(ctx, llm, only=args.only, limit=args.limit)
    if isinstance(ctx.adapter, FileExportAdapter):
        drafted = [aid for aid, st in ctx.state.activities.items() if st.post_id is not None]
        print(f"WordPress import file: {ctx.adapter.write_wxr(drafted)}")
    print(rep.final_text)
    print(f"\n[{len(rep.tool_calls)} tool calls, {rep.tokens} tokens]")


def cmd_review(args):
    from .agents.reviewer import summarize
    from .llm import from_env

    if not Path(args.state).exists():
        sys.exit(f"No state file {args.state}: run `cdp migrate` first.")
    print(summarize(StateStore(args.state), from_env() if args.llm else None))


def cmd_approve(args):
    from .pipeline import approve

    ctx = build_ctx(args)
    a = ctx.state.activity(args.activity_id)
    if a is None:
        sys.exit(f"No activity {args.activity_id} in {args.state}")
    if not args.yes:
        ok = input(f"Approve {a.number} {a.title} as it is now, after checking it yourself? [y/N] ")
        if ok.strip().lower() != "y":
            sys.exit("Not approved.")
    print(f"Approved version {approve(ctx, args.activity_id)[:12]}. Run `cdp migrate --only {args.activity_id}`.")


def cmd_new_activity(args):
    ctx = build_ctx(args)
    if ctx.llm is None:
        sys.exit("Set ANTHROPIC_API_KEY, or use the no-AI form described in skills/toolkit-activity-publisher/SKILL.md.")
    ctx.allow_document_mode = True
    text = Path(args.file).read_text()
    for step, extra in (("extract_activity", {"document_text": text}), ("validate_activity", {}),
                        ("check_fidelity", {}), ("scan_pii", {}), ("create_draft", {})):
        out = T.call(ctx, step, {"activity_id": args.activity_id, **extra})
        print(f"{step}: {json.dumps(out)[:400]}")
        if "error" in out or out.get("ok") is False:
            print("Stopped. Run `cdp review` to see what to fix.")
            return
    print("Draft created. Review it in WordPress, then publish.")


def cmd_redirects(args):
    """Rebuild out/redirects.csv from the live permalinks of published activities."""
    import csv
    from urllib.parse import urlparse

    if args.target != "wordpress":
        sys.exit("Use --target wordpress: redirects are read from the published pages.")
    ctx = build_ctx(args)
    rows, missing = [], []
    for aid, st in sorted(ctx.state.activities.items()):
        if st.post_id is None:
            continue
        link = ctx.adapter.published_link(st.post_id)
        if link:
            rows.append((f"/items-1/{aid}", urlparse(link).path))
        else:
            missing.append(aid)
    ctx.out_dir.mkdir(parents=True, exist_ok=True)
    with open(ctx.out_dir / "redirects.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "target", "regex", "code"])
        w.writerows([(s, t, 0, 301) for s, t in rows])
    print(f"{len(rows)} redirects written to {ctx.out_dir / 'redirects.csv'}")
    if missing:
        print(f"Not published yet (no redirect): {', '.join(missing)}")


def cmd_evaluate(args):
    from .evaluation import live_eval, offline_eval

    rep = live_eval(args.results) if args.live else offline_eval(out_dir=args.results)
    print(json.dumps(rep.get("summary", rep), indent=1))
    print(f"Written to {args.results}/")


def cmd_agent_eval(args):
    from .evaluation import agent_eval
    from .llm import from_env

    llm = from_env()
    if llm is None:
        sys.exit("Set ANTHROPIC_API_KEY to run the agent evaluation.")
    rep = agent_eval(llm, n_activities=args.activities, seeds=tuple(args.seeds))
    Path(args.results).mkdir(parents=True, exist_ok=True)
    (Path(args.results) / "agent_eval.json").write_text(json.dumps(rep, indent=1))
    for arm, runs in rep["arms"].items():
        print(arm, [{k: v for k, v in r.items() if k != "report"} for r in runs])


def cmd_extraction_eval(args):
    from .evaluation import extraction_eval
    from .llm import from_env

    llm = from_env()
    if llm is None:
        sys.exit("Set ANTHROPIC_API_KEY to run the extraction evaluation.")
    rep = extraction_eval(llm, n=args.n)
    Path(args.results).mkdir(parents=True, exist_ok=True)
    (Path(args.results) / "extraction_eval.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: v for k, v in rep.items() if k != "rows"}, indent=1))


def main(argv=None):
    p = argparse.ArgumentParser(prog="cdp", description="CDP Toolkit migration")
    p.add_argument("--state", default="state.json")
    p.add_argument("--cache", default=".cache/http")
    p.add_argument("--out", default="out")
    p.add_argument("--export-dir", default="export")
    p.add_argument("--target", choices=["file", "wordpress"], default="file")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between requests")
    p.add_argument("--results", default="eval/results")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inventory", help="list Toolkit activities").set_defaults(fn=cmd_inventory)
    m = sub.add_parser("migrate", help="run the fixed pipeline (no LLM)")
    m.add_argument("--only", nargs="*")
    m.add_argument("--limit", type=int)
    m.set_defaults(fn=cmd_migrate)
    a = sub.add_parser("agent", help="run the Claude orchestrator agent (one session per activity)")
    a.add_argument("--only", nargs="*")
    a.add_argument("--limit", type=int)
    a.set_defaults(fn=cmd_agent)
    r = sub.add_parser("review", help="what needs a person, in plain words")
    r.add_argument("--llm", action="store_true", help="let the reviewer agent write the summary")
    r.set_defaults(fn=cmd_review)
    ap = sub.add_parser("approve", help="approve the current version of a blocked activity")
    ap.add_argument("activity_id")
    ap.add_argument("--yes", action="store_true")
    ap.set_defaults(fn=cmd_approve)
    n = sub.add_parser("new-activity", help="turn an activity document into a checked draft")
    n.add_argument("file")
    n.add_argument("--activity-id", required=True)
    n.set_defaults(fn=cmd_new_activity)
    sub.add_parser("redirects", help="rebuild out/redirects.csv from published permalinks").set_defaults(fn=cmd_redirects)
    e = sub.add_parser("evaluate", help="offline evaluation (synthetic), or --live on the real site")
    e.add_argument("--live", action="store_true")
    e.set_defaults(fn=cmd_evaluate)
    ae = sub.add_parser("agent-eval", help="agent with versus without guardrails (needs ANTHROPIC_API_KEY)")
    ae.add_argument("--activities", type=int, default=6)
    ae.add_argument("--seeds", type=int, nargs="+", default=[3, 4, 5])
    ae.set_defaults(fn=cmd_agent_eval)
    xe = sub.add_parser("extraction-eval", help="extraction agent accuracy on 46 documents (needs ANTHROPIC_API_KEY)")
    xe.add_argument("--n", type=int, default=46)
    xe.set_defaults(fn=cmd_extraction_eval)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
