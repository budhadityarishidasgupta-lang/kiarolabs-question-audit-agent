# Audit Agent

`audit-agent` is a repo-hosted Python tool for auditing question generation and answer validation across:

- `budhadityarishidasgupta-lang/Teacher-Application-`
- `budhadityarishidasgupta-lang/english-spelling-trainer`
- `budhadityarishidasgupta-lang/kiarolabs-membership-service`

The goal is accuracy:

- verify what the source apps send
- verify how the membership service generates questions
- verify that answer validation matches the backend source of truth
- produce a report with findings, evidence, and follow-up actions

## What Changed In This Version

Version `0.2.0` moves the scaffold closer to a real audit agent:

- phase-based orchestration through an agent loop
- canonical contract registry for more objective checks
- richer structured findings with IDs, categories, expected vs observed behavior, and confidence
- GitHub API caching to reduce repeated fetches
- `--dry-run` mode for safer setup validation
- reproducible report metadata including version and config hash

## Requirements

- Python `3.11+`
- No third-party Python packages are required for non-DB modes

Optional for DB mode:

- `psycopg` or `psycopg2`

Optional:

- `GITHUB_TOKEN` for GitHub mode
- `AUDIT_DB_URL` for DB audit mode

## Project Layout

Key files:

- [main.py](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/main.py)
- [ARCHITECTURE.md](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/ARCHITECTURE.md)
- [canonical_contract.json](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/config/canonical_contract.json)
- [audit_targets.json](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/config/audit_targets.json)
- [audit_targets.github.json](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/config/audit_targets.github.json)
- [runner.py](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/src/audit_agent/runner.py)
- [agent_loop.py](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/src/audit_agent/agent_loop.py)

## Repo-Local Skills

I added a small set of repo-local skills under [skills](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/skills) to help future Codex instances extend this agent consistently.

Included skills:

- [github-repo-ingestion](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/skills/github-repo-ingestion/SKILL.md)
- [ast-contract-extractor](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/skills/ast-contract-extractor/SKILL.md)
- [canonical-contract-validator](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/skills/canonical-contract-validator/SKILL.md)
- [semantic-code-searcher](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/skills/semantic-code-searcher/SKILL.md)

I did not split `audit-orchestrator` and `audit-report-generator` into skills because those are better owned by the codebase itself:

- orchestration belongs in the runtime modules
- reporting belongs in the report renderer and CLI

Those two are implementation surfaces, not reusable operator workflows.

## Execution Modes

### Local Mode

Scans local repository checkouts. Use this when the repos exist side by side in the same workspace.

Recommended layout:

```text
/workspace
  /audit-agent
  /Teacher-Application-
  /english-spelling-trainer
  /kiarolabs-membership-service
```

Because the config file lives under `audit-agent/config`, sibling repositories should usually be referenced with `../../repo-name`.

Run:

```bash
python main.py --config config/audit_targets.json
```

### GitHub Mode

Scans repository contents through the GitHub REST API and does not require local clones.

Set the token:

```bash
GITHUB_TOKEN=your_token
```

Recommended GitHub fine-grained permissions:

- `Contents: Read`
- `Metadata: Read`

Run:

```bash
python main.py --config config/audit_targets.github.json
```

Debug the scan plan without fetching blobs:

```bash
python main.py --config config/audit_targets.github.json --dry-run
```

Fail CI for serious findings:

```bash
python main.py --config config/audit_targets.github.json --fail-on critical,high
```

### DB Mode

Runs a read-only Postgres schema and readiness audit against the configured database.

Set the connection string:

```bash
AUDIT_DB_URL=postgresql://user:password@host:5432/dbname
```

Run:

```bash
python main.py --mode db
```

Maths-specific DB audit:

```bash
python main.py --mode db-math
```

Maths migration preview:

```bash
python main.py --mode db-math-migration-check
```

Use a different environment variable name if needed:

```bash
python main.py --mode db --db-env-var MY_AUDIT_DB_URL
```

Outputs:

- `reports/db-audit-latest.md`
- `reports/db-audit-latest.json`

DB mode is inspection only:

- it does not run migrations
- it does not alter schema
- it does not insert, update, or delete rows
- it fails safely if the configured DB environment variable is missing

### GitHub Actions DB Audit

The GitHub Actions workflow supports choosing the audit mode at dispatch time.

Recommended maths sequence:

1. Run `db-math`
2. Review table existence, columns, and sample rows
3. Run `db-math-migration-check`
4. Use those results to draft additive migration SQL

## Config Schema

Top-level config fields:

- `audit_name`: report name
- `mode`: `local` or `github`
- `targets`: list of repositories to audit
- `checks`: scan controls and audit heuristics

Each target requires:

- `name`
- `role`: `source_app` or `generator_service`
- `repo`

Local mode targets also need:

- `path`

GitHub mode targets can optionally set:

- `branch`

Important `checks` fields:

- `include_extensions`: file extensions to scan
- `exclude_path_contains`: path fragments to skip
- `max_files_per_repo`: GitHub mode fetch cap after prioritization
- `required_source_patterns`: signals expected in question or answer flows
- `high_risk_terms`: correctness-related terms that increase confidence when present

## Canonical Contract

The source of truth lives in [canonical_contract.json](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/config/canonical_contract.json).

This defines:

- required question fields
- optional question fields
- supported question types
- required answer fields
- expected normalization vocabulary
- severity policy guidance

The agent compares observed code signals against that contract and flags drift.

## Report Format

Each run writes:

- `reports/latest-report.md`
- `reports/latest-report.json`
- `reports/<audit_name>.md`
- `reports/<audit_name>.json`

DB mode additionally writes:

- `reports/db-audit-latest.md`
- `reports/db-audit-latest.json`

Each report includes:

- audit metadata
- version and config hash
- structured findings
- errors
- notes

Each finding includes:

- finding ID
- severity
- category
- repo and path
- expected behavior
- observed behavior
- evidence
- recommendation
- confidence
- auto-fixable flag

## Error Handling

The agent reports errors rather than crashing the whole run where possible.

Examples:

- missing local checkout
- missing `GITHUB_TOKEN`
- GitHub tree fetch failure
- blob fetch failure for individual files

Phase errors are recorded in the report under `Errors`.

## Logging And Caching

Current behavior:

- progress and summary go to stdout
- detailed run artifacts go to `reports/`
- GitHub API responses are cached under `.cache/github/`

The cache reduces repeated GitHub API calls during iterative runs.

## Testing The Agent

Current low-friction verification steps:

1. Run local mode with missing repos and confirm the agent emits explicit missing-checkout findings.
2. Run GitHub mode without `GITHUB_TOKEN` and confirm the agent emits a clear auth finding.
3. Run GitHub mode with `--dry-run` to inspect which repos and paths would be scanned.
4. Run with `--fail-on critical,high` and verify CI-style exit behavior.

## CI

A starter workflow is included at [audit.yml](C:/Users/bda50/Documents/Codex/2026-04-22-question-can-i-create-a-new/audit-agent/.github/workflows/audit.yml).

It currently runs a dry run on a schedule or manual trigger. Once repository access and tokens are wired in, it can be expanded to run the full audit and upload the report artifacts.

## Current Limits

This is still a code-and-structure audit, not a runtime certifier.

It does not yet:

- parse ASTs for Python or TypeScript
- replay API fixtures against staging
- analyze Git diffs or PR deltas
- post PR comments automatically

It can now perform a read-only Postgres readiness audit in DB mode, but it still does not execute migrations or recommend destructive changes.

Those are the best next upgrades once the GitHub-driven contract audit is stable.
