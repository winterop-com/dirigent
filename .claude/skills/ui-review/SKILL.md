---
name: ui-review
description: Walk a UI change against docs/ui-conventions.md with the live browser before its PR merges
---

# UI review — the pass every UI PR gets before merging

Run this against the CHANGED SCREENS of a UI branch, in the live browser against a seeded
instance, before the PR is merged. Findings block the merge until fixed or explicitly waived
by the owner.

## How

1. Build the branch (`bun run build` — the e2e and the browser serve `dist`, and a stale
   bundle reviews the wrong code) and open every screen the diff touches, dark palette first,
   then light.
2. Walk the checklist below per screen. Screenshot anything that fails.
3. Small findings: fix on the branch. Judgment calls: put them to the owner before merging.

## The checklist (each rule lives in docs/ui-conventions.md — read it first)

- **Zero-noise**: no rendered zero counts, no columns that are almost always empty or almost
  always identical, no empty-state lectures (state the fact; name a way in only when it is
  not on the screen), no fact said twice on one screen.
- **Identity quartet**: title is the name if there is one else the code; the code is always
  on screen in mono and never drawn twice; nothing is referenced by name.
- **Copy voice**: terse, data-first product English. Normal words — creates, not mints; no
  "yet" on settled things; no plumbing words (streams, tails) in user-facing lines; states
  are lowercase words everywhere. The context says most of it: no screen subtitles, no
  static status-bar notes, no gloss under a heading whose table has headers — a sentence
  survives only by adding a fact.
- **A copy defect is a pattern, not an instance**: on finding ONE bad line, run
  `uv run python scripts/ui_copy.py` — the inventory of every sentence the UI renders —
  and read it END TO END, fixing every occurrence in the same change. A grep for the
  patterns you remember is not a sweep; the login screen proved it.
- **Controls**: nothing wears interactive chrome unless it does something; a visible primary
  action is not narrated elsewhere; buttons disable with a title saying why; `New` alone
  where the screen names the noun (full name on aria-label and palette).
- **Fields**: inputs sit on the `--field` ground with a visible border in BOTH palettes;
  program-carrying fields are code editors; required errors appear after interaction, not on
  open.
- **Layout**: seams align across the shell's strips; long text truncates with the full value
  on hover (`w-full max-w-0` lead cells); lists scroll inside their shell with sticky headers
  and the scrollbar starting below them; nothing wraps a toolbar.
- **Graphs**: fit-view shows everything at a readable scale; status colors are the only color
  voice on nodes; selection is neutral; edges are visible in both palettes.
- **Panels**: a screen owns its panel — content and open tab reset on screen change; an
  unfilled panel does not render.

## After

Note in the PR body that this pass ran and what it changed.
