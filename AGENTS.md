# AGENTS.md

Guidance for coding agents working in this repository.

## Agent skills

### Issue tracker

Issues, specs and tickets live as **GitHub issues** in `adorablebrillo/the-shelf` — create, read, list and label them with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, label strings equal to their names (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), applied as GitHub labels via `gh issue edit --add-label`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
