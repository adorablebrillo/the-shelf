# Settings

## Sub-features

- The Shelf tab: OpenRouter key, model picker, save, curate now with its status line.
- The Book brew tab: the meter (a half-circle gauge, one arc per interest that is on, sized by its dial, the needle on the widest; it redraws with every dial change and is the same drawing as the survey's last step) above one card per interest — dial, mode, books — then never-show chips and picks per issue. Every change saves at once.
- The Authors tab: watched authors with lanes, add and remove, the empty state.
- The Import tab: choose a Goodreads export, preview with series ticks, import (adds books + marks, no web lookups).

## How to get to it (user POV)

Tap **Settings** in the section bar. The page (not a modal) replaces the view; the nav's other sections still work.

## Driving it with chrome-devtools-axi

- Tab order and arrow keys: click a tab, press ArrowRight/ArrowLeft; focus must follow.
- `curate now` runs the pipeline (network + a model key) — with the dead-proxy launch it fails honestly into the status line; do not treat that as a Settings bug.
- The import tab reads a real Goodreads CSV: drive it with a tiny made-up export (columns `Title,Author,Book Id,My Shelf,Date Read,Date Added`) if a task touches the import; otherwise seed `added-books.json` directly.

## Gotchas

- The settings script binds on view enter and stops its poll on leave — verify no stale status poll survives a view change (console/network should quiet down).
- The key field is a password input outside a form by design; Chrome logs a verbose DOM notice about it. That pre-existing notice is not an error.
