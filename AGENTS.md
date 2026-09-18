# AGENTS.md

Guidance for coding agents working in this repository.

## Agent skills

### Issue tracker

Issues, specs and tickets live as **GitHub issues** in `adorablebrillo/the-shelf` — create, read, list and label them with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, label strings equal to their names (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`), applied as GitHub labels via `gh issue edit --add-label`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Pull requests

Every ticket ships as a **pull request** — do not push straight to `main`. Branch
per ticket (`ticket-<n>-<slug>`), PR title = the ticket title, and the PR body
links its ticket with `Closes #<n>` so merging closes the issue and unblocks
whatever depended on it.

**Every PR body shows the change visually.** Use the `before-and-after` skill
(`~/.hermes/.agents/skills/before-and-after`) to attach media and keep exactly one
marked block in the description:

- **Front-end / UI work**: a real before/after pair of the same view — same
  viewport, same state, and equal pixel height so the tops align in the rendered
  table.
- **Everything else**: still visual. A diagram of the change (flow, sequence,
  state) or a before/after of the data, so a reviewer sees the change without
  reading the diff.
- Put the evidence near the top of the body, before implementation details, and
  never rewrite the surrounding prose — the formatter replaces only its own
  `<!-- before-and-after:start/end -->` block.

Captures are staging only (`captures/` is git-ignored); publishing uploads them
and rewrites the references to GitHub attachment URLs.
