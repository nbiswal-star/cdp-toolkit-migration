# CDP Toolkit Migration

Group 19, Intro to AI (Fall 2026), Carnegie Mellon University, Heinz College.
Client: Interactivity Foundation (IF), Collaborative Discussion Project.

**For IF in one paragraph.** This tool copies each Toolkit activity to your WordPress site as
an unpublished draft, word for word. Nothing appears on your site until your staff click
Publish. Nothing has been installed on your site, and no Toolkit content has been sent to an
AI service: both wait for your approval. Your staff also get a step-by-step guide for adding
and revising activities, with or without AI.

## Status (November 1, 2026)

| Part | State |
|---|---|
| Nine agent tools and the fixed-order pipeline | Built; tested offline on synthetic data |
| Three agents (orchestrator, extraction, reviewer) | Built; tested with scripted model turns only, not yet with a live model |
| WordPress plugin | Built; tested on a local WordPress 6.5 site only, not yet with Breakdance, FacetWP, MySQL, or IF's host |
| Skill folder for IF staff | Built; not yet tried by IF staff |
| Offline evaluation | Done, results below |
| Run on the live Toolkit | **To do**: `cdp evaluate --live` on a computer that can reach the Toolkit site |
| Agent and extraction evaluations with a live model | **To do**: `cdp agent-eval` and `cdp extraction-eval` need an Anthropic API key |
| Plugin on IF staging, Claude consent, staff usability test | **To do**: needs IF |

The documents in `docs/` are the TP1 submissions from early October (team contract, client
meeting prep, scope statement Version 1, slides for October 8). The agent descriptions in the
scope Objective and slide 3, and the team roles, were corrected on November 1 to match the
build. The technical plan Version 3 describes this build. The October 8 decisions and scope
Version 2 are tracked on the project board.

## How it works

Every Toolkit activity page embeds its own Wix CMS record (structured fields, rich text, time,
module, tags, PDF link). The tools read that record directly, so activity wording is copied by
code, not re-typed by AI. The structure of all 46 pages was read on November 1, 2026 through a
browser (field names, rich-text node types, step heading forms, times, tags; no activity
wording was stored). That profile is in `eval/live_structure_2026-11-01.json`. The full
migration has not yet run against the live site.

```
Wix Toolkit ──> crawl_toolkit ──> fetch_page ──> extract_activity ──> validate_activity
                                                                          │
WordPress draft <── create_draft <── rehost_asset <── scan_pii <── check_fidelity
      │
      └──> check_links (and the old-to-new link list)       IF staff review and publish
```

- **Orchestrator agent** (Claude, our own tool-use loop on the Messages API): one short session
  per activity. It runs the tools, retries within limits, and sends failures to human review.
  It acts only through the tools and cannot publish. `cdp migrate` runs the same tools in a
  fixed order without any LLM.
- **Extraction agent** (Claude, no tools): turns a free-form activity document into the
  activity fields for the update workflow (`cdp new-activity` only; the orchestrator cannot
  use it). `check_fidelity` verifies every line against the document.
- **Reviewer agent** (Claude, no tools): explains blocked or flagged activities to staff in
  plain words (`cdp review --llm`; a fixed template is used without an LLM).

The model is set with `CDP_MODEL` (default `claude-sonnet-4-5`).

## The nine tools

Each tool is a Python function in `src/cdp_migration/tools/`. Its docstring is sent to the model
as the tool description (purpose, when to use it, preconditions, returns, failure handling), and
its type hints become the input schema. Rules in docstrings are also enforced in code.

| Tool | What it does | Rule enforced in code |
|---|---|---|
| `crawl_toolkit` | lists all activity pages from the five module pages | allow-listed hosts (redirects checked too), 1 request per second |
| `fetch_page` | reads one page's embedded Wix record | comments never stored; commenter names kept only as a PII deny list |
| `extract_activity` | builds the Activity record by fixed mapping | clears earlier QA results |
| `validate_activity` | Toolkit rules (number, module, time, level, goals, step numbering, unreadable steps, unsupported content) | errors block |
| `check_fidelity` | every field equals the source in order (apart from whitespace); nothing dropped; links, embeds, images, level, tags, module, PDF, step times match | differences block, with word-level diffs |
| `scan_pii` | emails, phones, commenter names, text aimed at AI systems | flags route to a person |
| `rehost_asset` | copies the PDF, main image, and images inside the text to WordPress | only after the checks pass; each file uploaded once (SHA-256) |
| `create_draft` | creates or updates the one draft per activity (embeds are rewritten to the form WordPress keeps) | needs every check passed or a person's approval of this exact version; draft only; never overwrites a published post; reads the saved post back and reports any content WordPress removed |
| `check_links` | checks every link's status without downloading it; writes `out/redirects.csv` | public http(s) addresses only |

## Safety guardrails

Each layer can be switched off on its own for the evaluation (`src/cdp_migration/guardrails.py`).

- **Fidelity gate**: any change to wording, order, links, embeds, numbers, or metadata blocks the record.
- **PII and instruction gate**: personal data or text such as "ignore previous instructions"
  sends the record to a person. The text is kept, never acted on.
- **Approval and hash gate**: `rehost_asset` and `create_draft` take only an activity ID, load
  the approved record, and refuse if it failed a check or changed after QA. The checks find
  problems; this gate is what stops them. That is why switching it off lets everything through.
- **Draft only, three times over**: no tool can publish; adapters refuse any other status; and
  the WordPress **CDP Drafter** role has no publish permission (WordPress refused the drafter's
  publish attempt in `eval/results/wordpress_integration.txt`).
- **Limits**: domain allow list, tool-call, retry, and token caps for the agent.
- **Human approval**: `cdp approve <id>` is for people only; the agent has no such tool.

## Evaluation

`cdp evaluate` runs offline on a synthetic Toolkit: 46 activities whose structure matches the
live profile (module sizes, 3 to 8 steps, 35 to 65 minutes, step times adding up to the total,
the live tag list and rich-text node types; checked by `tests/test_synthetic_quality.py`), with
wording from a fixed phrase bank, so no IF content is copied. Results:
[`eval/results/offline_eval.md`](eval/results/offline_eval.md).

Clean run: 46 of 46 activities drafted, 0 good records blocked, fidelity pass rate 1.0.

On the live Toolkit, 37 activities contain 58 Wix HTML text boxes (for example "Online
Adaptation" notes). They contain only paragraphs, bold text, and links, no slides or video.
The migration turns each into a callout block whose words are checked like all other text
(`tests/test_fidelity_mutations.py`). Run against the 46 live records on November 2, 2026, all
46 passed validation, fidelity, and PII checks.

Planted problems let through to a draft:

| Configuration | Let through |
|---|---|
| All guardrails on | 0 of 9 |
| Fidelity gate off | 5 of 9 |
| PII and instruction gate off | 3 of 9 |
| Approval and hash gate off | 9 of 9 |
| All guardrails off | 9 of 9 |

The nine planted problems: changed step time, dropped step, paraphrased goal, one inserted "not",
dropped journal prompt, instruction to the AI on the page, email address, commenter name, and a
record edited after the checks passed. `tests/test_fidelity_mutations.py` adds 18 more changes
(swapped goals, moved text, changed link, replaced embed, flipped level, and others); all are caught.

Limits: synthetic data, one seed, and the planted problems were written knowing how the checks
work. These numbers test the code gates, not the model. The model measurements still to run:

```bash
export ANTHROPIC_API_KEY=...
cdp agent-eval            # orchestrator in three arms (guardrails on; code gates off with the safety prompt; code gates off with a plain prompt), 3 seeds
cdp extraction-eval       # extraction agent on 46 documents: share passing check_fidelity
cdp evaluate --live       # on a computer that can reach the Toolkit
```

Results are written to `eval/results/` and are meant to be committed.

## Data protection and simulated data

- The repository is private. Run outputs (`state.json`, `export/`, `out/`, `.cache/`) are
  git-ignored because they contain IF content; delete them at handover.
- Ratings and comments are never copied. Commenter names are kept in `state.json` only to check
  that none leaked, and are deleted with it.
- IF's consent is needed before Toolkit content is processed with Claude. The fixed migration
  path (`cdp migrate`) uses no LLM.
- Credentials come from environment variables only. The WordPress application password belongs
  to the CDP Drafter account and should be revoked after the migration.
- Synthetic data comes from `src/cdp_migration/synthetic.py`; its quality checks are in
  `tests/test_synthetic_quality.py`.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,agent]"
python -m pytest              # tests; WordPress tests run when CDP_WP_URL is set
cdp evaluate                  # offline evaluation

# On a computer that can reach collaborativediscussionproject.com:
cdp inventory                 # list the 46 activities
cdp migrate                   # file export: export/ and a WordPress import file
cdp review                    # what needs a person, in plain words
cdp evaluate --live           # real-site evaluation, writes eval/results/live_eval.json

# WordPress target (see wordpress/README.md):
export CDP_WP_URL=... CDP_WP_USER=drafter CDP_WP_APP_PASSWORD=...
cdp --target wordpress migrate --limit 5

# With an Anthropic API key (after IF consents):
cdp agent --limit 5           # orchestrator agent, one session per activity
cdp --target wordpress redirects   # after IF publishes: old-to-new link list from the live addresses
cdp --target wordpress new-activity activity.txt --activity-id 2-11-short-name
```

## Try it on your computer

This puts all 46 activities as drafts on a practice WordPress site on your computer. You need
Docker Desktop (running), Python 3.10 or later, and internet access to the old Toolkit.

```bash
pip install -e ".[dev]"
cd wordpress
docker compose up -d
./setup-local.sh              # prints CDP_WP_URL, CDP_WP_USER and CDP_WP_APP_PASSWORD
cd ..
export CDP_WP_URL=http://localhost:8899 CDP_WP_USER=drafter CDP_WP_APP_PASSWORD='<paste the password the script printed>'
cdp --target wordpress --state state-wp.json migrate
```

Expected result: `Drafted: 46   Needs review: 0`. If you run it again, it updates the same
drafts. It does not make copies. `cdp --state state-wp.json review` explains any activity that
needs a person.

To see the drafts, open http://localhost:8899/wp-admin and log in:

| | |
|---|---|
| Username | `admin` |
| Password | `change-me-now` |

This login is a default for the practice site only. Never use it on a real site. To set a different
password on the first install, run `ADMIN_PASSWORD='...' ./setup-local.sh`. To change it later, run
`docker compose run --rm cli wp user update admin --user_pass='...'` in `wordpress/`.

Go to **Toolkit Activities** and click **Preview** on a draft. The Toolkit's text boxes show as
shaded callouts with their bold text and links. The Modules, Levels and Tags columns show the
filters. The drafter account cannot publish.

Notes:

- The application password is a real login token. Do not put it in a file or commit it.
  `setup-local.sh` makes a new one each time you run it.
- `state-wp.json` records what was drafted. Git ignores it.
- If `pip` fails with an `expat` or `pyexpat` error, your Python install is damaged. Use a
  different Python (for example `python3.11 -m pip ...`) or run `brew reinstall python expat`.
- To remove the practice site and its data, run `docker compose down -v` in `wordpress/`.

More detail, and a way to run without Docker: [wordpress/README.md](wordpress/README.md).

## Repository layout

```
src/cdp_migration/     tools, agents, pipeline, adapters, evaluation, CLI
tests/                 tests; test_wordpress_live.py runs against a real WordPress
skills/                toolkit-activity-publisher skill (SKILL.md, template, checklist, examples, schema)
wordpress/             cdp-activity plugin; local site setup (Docker, or PHP with SQLite)
eval/                  live structure profile and evaluation results
board/                 GitHub Projects board setup script and cards
docs/                  TP1 documents and technical plan (LaTeX and PDF)
scripts/publish.sh     creates the GitHub repo, adds the collaborator, builds the board, links it in the docs
```

## Team

| Member | Role |
|---|---|
| Joshua Kalakoti | Client communication |
| Like Cui | Documentation |
| Nibedita Biswal | Technical build, team coordinator |
| Letu Wang | Technical build |
| Yinfeng Liu | Technical build |

All Toolkit content belongs to IF. Ownership and licensing of the code, and transfer of this
repository to an IF account, will be agreed with IF in writing before handover. Client details
are confidential; do not share outside the team, IF, and course staff without IF's permission.
