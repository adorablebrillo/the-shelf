# Archive

## Sub-features

- Read & loved: everything marked read or loved — by series runs, standalones with thumbnails.
- The stacks: a bookcase of spines; hover/peek shows the plate (never a native tooltip), a second deliberate tap puts a book back on the shelf.
- Not for me: set-aside books; pressing `not for me` again returns one (a pick returns to Home as open, an added book leaves the shelf).
- Tabs switch with arrow keys (roving focus).

## How to get to it (user POV)

Tap **Archive** in the section bar, then the `READ & LOVED` or `NOT FOR ME` tab.

## Driving it with chrome-devtools-axi

- Mark a pick `not for me` on Home; open the Archive's Not for me tab and click the lit mark again; the pick returns to Home as open (confirm in `reader-state.json`).
- On a phone, tapping a stack spine peeks its title; a second tap (after 600 ms) un-reads the book. On desktop a single click un-reads.
- An added book un-read this way leaves the shelf entirely (its record stays in `added-books.json`).

## Gotchas

- Marks made in the Archive behave exactly like marks anywhere else — the Archive is a view, not a separate store.
- The stacks' plate is an in-page element; native browser tooltips are deliberately absent.
