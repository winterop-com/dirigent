# UI conventions

The web UI is a single-page bundle served by the API server itself, from
`packages/dirigent-server/frontend`. This page is authoritative for how it is built; where the
code disagrees with this document, one of the two is a bug.

Nothing here is about what the screens show. That is decided per screen, from a design board,
and each one arrives as its own change. What follows is the frame every screen is built inside.

## The stack

| Piece | What | Why it and not the obvious alternative |
| --- | --- | --- |
| Build | vite 8, TypeScript 7 with project references | `tsc -b` gates the build, because vite strips types without checking them |
| UI | React 19, react-router 7 with `BrowserRouter` | The server answers a navigation nothing claimed with the shell, so paths stay clean and a deep link can be pasted |
| Styling | Tailwind v4, CSS-first | There is no `tailwind.config.js` and there must not be one -- the theme lives in `src/index.css` under `@theme` |
| Components | shadcn on **Base UI** (`@base-ui/react`), style `base-nova` | The generated files in `src/components/ui/` are pristine and never hand-edited |
| Graphs | `@xyflow/react` for the canvas, `elkjs` for the layout | React Flow draws what it is given and decides no geometry; elk's layered algorithm is what places a DAG. Both are loaded lazily -- see below |
| Editor | `monaco-editor` with `monaco-yaml` | A pipeline document is YAML checked against a schema, and squiggling an unknown key where an apply would refuse it needs a language server rather than a textarea. Its own lazy chunk, behind `CodePane`, which is what every screen that writes source mounts -- a document, and a config field whose schema says it carries a program |
| YAML | `yaml` | A document crosses the wire as JSON and is written by people as text, so both screens that touch one parse or render it here. The apply dialog imports it inside its handler; the editor's source pane has it in its own chunk |
| Markdown | `marked`, for its lexer only | A description is authored markdown and has to render as prose. Nothing here produces an HTML string, so what is drawn is a token tree React escapes -- see `lib/markdown` |
| Palette | cmdk | |
| Toasts | sonner | |
| Mode | next-themes, `class` strategy | |
| Fonts | IBM Plex Sans and IBM Plex Mono, self-hosted through `@fontsource` | No CDN: a UI served from a private network has to work on one |
| Lint | oxlint, plus `scripts/check_ui_classes.py` | A JS linter cannot see inside a `className`, so the type scale gets a check of its own |
| Format | oxfmt, pinned exactly, configured in `.oxfmtrc.json` | Prettier's output from the linter's own project, and it sorts Tailwind classes against `src/index.css` rather than guessing at the theme |
| Tests | vitest in `environment: node`, playwright for the browser | |
| Packages | **bun**, always. Never npm, yarn, or pnpm | |

**Base UI is the primitive layer, and app code never imports it.** Pages and components import
from `@/components/ui/*` and nothing else reaches for `@base-ui/react` directly. That boundary is
what lets the component layer be swapped without a change anywhere above it, and other apps in
this family are on a different primitive underneath the same imports.

**A screen whose dependencies no other screen has is a lazy route.** React Flow and elk together
are larger than the whole of the rest of this bundle, and only the two graph screens -- run
detail and the pipeline editor -- draw one, so `src/App.tsx` reaches both through `React.lazy`
and a `Suspense` whose fallback is the same `PageState` loading card every read shows. The entry
chunk is what every reader pays for on every screen; anything that only one screen needs belongs
in that screen's own chunk -- which is also why the connections and triggers screens are lazy,
each carrying the form, the dialogs and the panels nothing else uses.

**A chunk inside a lazy route is the same rule again.** Monaco is larger than React Flow and elk
put together, and three places write source in it -- the pipeline editor's source pane, the apply
dialog on the listing, which is not a lazy route at all, and a step config field whose schema
published a `contentMediaType`. All three mount `CodePane`, and that is the one `React.lazy`
reaching `CodeEditor`: opening a pipeline does not fetch an editor, opening its source tab or a
jq step does, and the dialog costs the entry chunk the few hundred bytes of a `Suspense`
rather than a megabyte of editor. Only the editor and the two contributions it hosts -- YAML and
shell -- are imported by path, `monaco-editor` as a whole registers seventy languages, and its two
web workers are `?worker` imports, which vite emits as chunks of their own.

**A chunk two screens want is fetched before either is asked for.** `warmEditor` is that same
import, fired by the shell once there is a session and the browser is idle -- `lib/idle` is
`requestIdleCallback` where there is one and a timer where there is not -- so the first source tab
or apply dialog of a session opens against a chunk that has already landed. Nothing waits on it,
it happens once, and the login screen is outside the shell and asks for none of it.

**oxfmt owns whitespace, quotes, semicolons and the order of Tailwind classes**, at four spaces,
single quotes outside JSX, no semicolons and a print width of 110. Nothing about that is worth an
opinion in review: run `make ui-fmt`. The generated files in `src/components/ui/` and
`components.json` are ignored, as they are in oxlint. `make ui-lint` runs the check first, so an
unformatted file fails the gate before anything else is read.

`make ui` builds the bundle, `make ui-dev` serves it with hot reload against a running `dg dev`,
`make ui-lint` and `make ui-test` are the gate, and `make ui-e2e` drives a real server in a
browser. The gate is wired into `make check` behind a check for bun, so a machine without bun
gets a loud skip rather than a failure.

## Three type sizes, and the named sizes outside them

The scale is 12px, 14px, and 16px. Nothing arrives beside it without a name.

| Class | Size | What wears it |
| --- | --- | --- |
| `text-xs` | 12px | Chips, badges, counts, timestamps, identifiers -- anything read at a glance rather than as prose |
| `text-sm` | 14px | Any sentence. The body size of the app |
| `text-base` | 16px | A page heading, and the command palette's search field |
| `text-stat` | 28px mono | A stat tile's number, and nothing else on any screen |
| `text-wordmark` | 48px | The login brand lockup's wordmark, and nothing else on any screen |
| `text-display` | 36px | The sign-in heading, and nothing else on any screen |

The wordmark is a brand mark rather than text: the login screen draws the product's name at
display size beside its tile, and no other screen may set a heading there.

`scripts/check_ui_classes.py` fails the gate on anything outside them, whether the fourth size
arrives as `text-[13px]` or as `text-lg`. The check has no allowlist -- it knows `text-stat`,
`text-wordmark` and `text-display` by name, and reads `index.css` itself so a fourth size cannot
be minted there either. A named
exception can be counted; an allowlist is a check people argue with. It skips
`src/components/ui/`, because those files are generated and regenerating them is how they are
fixed.

A relative size composes with the scale rather than escaping it, so `text-[0.85em]` on code inside
a sentence is deliberate and passes.

## Tokens

Everything colour is a CSS custom property in `src/index.css`, exposed to Tailwind through
`@theme inline`. Nothing anywhere else may write a colour.

**Two theme axes, kept apart.** The **mode** is light or dark: next-themes owns it, writes it as a
`dark` class on `<html>`, and follows the operating system until somebody says otherwise. The
**palette** is which set of colours the app spends inside that mode: `src/lib/theme.ts` owns it,
writes it as `data-theme` on the same element, and a small script in `index.html` applies it
before the first paint so there is no flash. Neither axis knows about the other.

**A palette is two blocks of CSS and one row, and nothing else in the app learns it exists.** The
blocks are `html[data-theme='<name>']` and `html.dark[data-theme='<name>']` in `index.css`, beside
the base ones; the row is in `PALETTES` in `src/lib/theme.ts`, carrying the name and the label.
**Each block answers to `[data-palette='<name>']` as well**, base palette included, so an element
inside the app can be painted in a palette the document is not wearing -- which is what a swatch
card is, and why a swatch cannot drift from the tokens it stands for. A test asserts the pre-paint script's list and that array
agree. Because a palette's selector outranks `.dark`, a token the base sets in both `:root` and
`.dark` has to be set in both halves of a palette that touches it at all -- a token set in the
light half alone leaks into the dark mode. A token a palette does not touch falls through to the
base, which is how a palette that only moves its surfaces keeps the status and kind hues.

**Both axes are chosen on the settings dialog's Theme pane**, and nowhere else. Appearance is
Light, Dark and System, one segmented control rather than a menu, because a choice from a fixed
set of three is one control and not a list to open. **Palette is three swatch cards**, because
what a palette is is what it looks like, and a card showing the ground, the surface, the line,
the ink and the accent says in one glance what a sentence under a segmented control took a
paragraph to approximate -- so no palette carries a line about itself any more. Neither row holds
a copy of what it sets -- Appearance writes next-themes, Palette writes `choosePalette`, and both
read back through the store. The topbar's toggle is the two-way flip over Appearance, and System
is reachable only here.

**Three palettes ship, ordered quiet to loud: `dirigent`, `paper`, `contrast`.** The default is
near-achromatic surfaces at hue 255; `paper` is the same app on warm paper with warm ink;
`contrast` is white on black and black on white with every line and every ink pushed to meet
4.5:1. **The amber is the identity hue in every one of them.** `--primary`, `--ring`,
`--terminal-accent` and the run status hues keep the hue they have; a palette moves the amber's
lightness only where its own ground needs it, and "one accent, spent where the app acts" holds
unchanged in all three. **The surface ladder keeps its order and roughly its steps** in every
palette, so a component designed against the rungs still reads -- except where a palette's whole
point is the ground it commits to, and `contrast` collapses page and card onto one white and one
black, drawing every card by its edge instead.

**The surface ladder** runs six rungs, and each one has to be seen: `--background` under
`--sidebar` under `--card` under `--secondary` (which is also `--input`), then two lines --
`--border` divides rows inside a panel, `--border-strong` separates panels. Ink runs
`--foreground`, `--muted-foreground` for a hint, `--faint` for a timestamp beside a name. Every
surface holds hue 255 at chroma at or below 0.017, so a long list reads as a surface.

**The identity colour is amber**, and it is spent on action and nothing else: a primary button,
the active rail entry, a focus ring. It sits on `--primary` / `--primary-foreground`, because that
is what every shadcn primitive reaches for. `--accent` keeps shadcn's own meaning -- the wash
under a pointer -- and is a quiet tint of the same hue.

**`--primary-ink` is the amber as text, and it is worn by the door's eyebrow and by a link.**
A fill is a ground with its own ink on it, so a light palette's `--primary` is taken down far
enough to carry light text and does not hold 4.5:1 as text itself; the ink twin is the same hue
taken further down until it does, and in a dark mode, where the accent already is an ink, it is
`--primary`. It is the same `-ink` pairing every status hue has. Behind the door the amber stays
a fill and an inline link's ink and nothing else: a link is a thing the reader can press, so it
wears the colour that means action, and it wears the ink twin because it is text. A screen that
set a heading, a label or a hint in it would be spending that colour on something nobody can
press.

**Status is named for the state machine.** `--status-succeeded`, `--status-failed`,
`--status-running`, `--status-waiting`, `--status-queued`, `--status-pending`,
`--status-completed-with-errors`, `--status-cancelled`, `--status-skipped`. The names are
`RunStatus` and `AttemptStatus` from `dirigent_client.enums`, so a status string off the wire
indexes a token with no translation table. Each has an `-ink` twin: the token fills a chip at 14%
alpha and the ink is what is legible on it -- the `.status-chip` class in `index.css` is that
rule, written once. `skipped` is drawn in neutral with a dashed edge, because a skipped step did
not happen and has not earned a colour.

Four semantic aliases sit over the top for anything that is not a run: `--good` is succeeded,
`--critical` is failed, `--warning` is completed-with-errors, `--info` is running. Each has an
`-ink` twin as well, for text on its own 14% fill.

**A kind is not a status, and has its own family of hues.** What a thing *is* -- a block kind, a
connection kind, the clock a schedule fires on -- takes `--kind-<family>` and the `.kind-chip`
fill rule, which is `.status-chip`'s written once more against tokens that cannot be confused
with a state. `lib/kinds` maps a kind to a family and hashes the ones this bundle was built
before, so the mapping is total and stable; no component writes a tint inline. Every family is
far from hue 80, because that hue is the identity colour and means action.

**Both modes, every time.** This app was designed dark first and the light one is its
inversion, not a second design: the same hues, the lightness ladder turned over. A token changed
on one side is checked on every surface that consumes it on the other -- a primary that reads as
the brand on near-black can read as mustard on near-white, a control filled by a rung that is a
clear step in one mode can be invisible in the other. `--primary` carries dark ink in the dark
mode and light ink in the light one, for that reason and no other. A palette is checked the same
way, on both of the modes it has.

**The app has one decorative element, and it is on the login screen.** The brand pane carries a
graph of steps above the lockup, filled in `--terminal-node` and edged in `--terminal-node-edge`
-- one and two surface rungs above the pane's own ground, per palette -- joined by
`--terminal-graph-edge` and set over arcs in `--terminal-graph-faint`. One run through it is lit
in `--terminal-accent`, with a glow under the lit links. One step wears `--status-failed`,
because a graph in which nothing ever goes wrong is not the graph this app draws, and the head,
the only solid node, wears `--status-completed-with-errors` under its halo: the state a run is
in when it reaches its end past a failed step, in the same token the run screen gives it. Nowhere else in the app is a shape drawn that does not
stand for something the reader can act on or read a value from.

**The brand pane is bounded.** It is 52% of the window, never under 560px and never past
1056px, the width at which the graph reaches its largest scale, so a display wider than that
spends what it gains on the form rather than on the mark. The two columns begin at `lg`, not
`md`: a window under 1024px cannot hold the pane's floor beside the form and its padding, and a
pane drawn narrower than its floor squeezes the graph into a strip. Between `lg` and `xl` the
pane holds that floor and the form column takes what is left; below `lg` the two stack and the
pane is a strip. The form pane bounds its form the same way and centres it, so what a wider
window buys that column is spent evenly either side of the one question it asks.

**The door's refusal takes no room.** A wrong password and a rate limit arrive as problem
documents, and the sentence is drawn in a critical-edged bar the height of a field, hung below
the button and positioned out of the flow: the form is centred in its column, so a notice that
took space would move every field the moment somebody got a password wrong. It is the one
refusal in the app not drawn by `Refusal`, for that reason alone.

**And the seam between the two is dragged.** It is a `separator` like every other dragged edge
here -- eight pixels of hit area over the line, drawn as nothing until a pointer, a focus ring or
a drag asks where it is, answering the arrow keys, Home and End as well as the pointer -- and it
moves between the pane's own two bounds, never past what the form column needs of the window. A
width somebody chose is that browser's from then on, kept as pixels rather than as a fraction for
the reason every panel here is: what they dragged it to was a decision about what is in it. A
double-click on the seam, or Delete on it, gives the pane its clamp back; a window that narrows
holds the choice inside the new bounds rather than forgetting it. Nothing else on any screen may
grow a handle this quiet -- a control nobody can find is a control nobody needs, and this one is
the door's alone.

**That graph is fitted to its box and centred in it.** The box is the pane's width from below the
top down to a fixed gap above the lockup, and it is measured; the drawing has a shape of its own
-- the table's extent plus its padding -- and it is scaled uniformly to fit, never past 1.5, so a
wide pane does not magnify it into a poster. A box taller than the fitted drawing gives the rows
up to 1.3 times their spacing and never the columns anything, because what a taller pane is worth
is a little more air between the ranks rather than a different graph; whatever height is still
over is ground, split evenly above and below. A box smaller than the shape needs is the one case
the drawing is spread across it and shrunk instead, which is what keeps a step's box off the one
beside it. The lockup and the facts are anchored to the foot of the pane, so neither moves between
a short pane and a tall one.

**The radius ladder** is 4px for a chip, 6px for a control and a card, 8px for a panel, stated in
`@theme` rather than derived. Tailwind's middle rungs are flattened onto it -- `rounded-md`
through `rounded-2xl` are all the card's 6px -- so a shadcn primitive that ships `rounded-xl`
lands on the ladder without being edited. The login's brand tile is the mark, not a card, and
keeps its own radius.

## `apiFetch` is the only fetch

`src/lib/api.ts` is the one place in this app that calls `fetch`. Every read goes through it, and
a page component that called `fetch` itself is a bug.

It exists because three things have to be right on every request and a page will silently get one
of them wrong: the versioned prefix, which this bundle cannot know at build time; the cookie
credential; and the fact that a refusal arrives as a problem document rather than as the resource.

The three shapes every resource module is written out of live here too -- `Page`, `Problem` and
`JsonMap` -- because a wire primitive declared twice is two of them, and a resource module that
had to import one from another resource module would say the two resources are related when they
are not.

- **The prefix is read, not written down.** `Settings.api_prefix` is configurable, so the server
  answers `GET /config.json` with the prefix this instance mounted at, and the bundle asks once.
  A caller writes the path the OpenAPI document writes -- `/pipelines`, `/auth/me` -- and never
  the prefix.
- **A refusal is an `ApiError`** carrying the problem document: `status`, `title`, `detail`,
  `problems`, `instance`. There is no `type` member; this server emits none, so nothing may key
  off one. `apiJson` throws it; `apiFetch` hands back the `Response` for a caller that cares about
  a particular status.
- **A path outside the versioned API is read through `rootFetch`.** The probes under `/health`
  answer at the root whatever prefix the API mounted at, and readiness answers 503 carrying the
  readiness document rather than a refusal -- so that one hands back the `Response` and lets the
  caller decide, and it lives here because this file is the only one that calls `fetch`.
  `lib/server-status` is its only caller and the only reader of the probe: the corner dot paints
  from that store and the settings dialog reads the same one, because two readers of one probe
  are two answers that can disagree on the same screen.
- **A 401 is the shell's, not a page's.** The session expired, and the answer is the login page
  rather than a refusal card on whatever happened to be open. The shell registers the redirect
  through `onUnauthorized`.

`src/lib/sse.ts` is the streaming half, and it is `fetch` plus a reader rather than `EventSource`:
the browser's own client cannot set the `Last-Event-ID` header these streams resume with, cannot
be aborted, and reconnects on its own schedule rather than the caller's. A caller passes a path
and gets frames -- event name, data, and the id the stream last stated -- and decides for itself
what `attempt`, `log`, `run`, `end` and `expired` mean. A stream ending is not a failure: `end`
says the run settled, and `expired` says the server closed the tail at its own wall-clock limit,
which `lib/run-stream` reopens from the cursor without showing the frame to the screen.

**One stream per open thing, never two.** `runs/{id}/$events` is already multiplexed, and the
server caps a principal at eight open streams: a second connection for a log pane would spend that
budget delivering the same story twice, with no ordering between the copies. `lib/run-stream` is
the loop that holds one open -- sequential by construction, so there is no path through it with two
in flight -- and its test double counts concurrent opens, which is what makes the rule fail a test
rather than a review. What a frame means is a pure reducer beside it, so a replay being idempotent
and a stale frame not moving a settled state backwards are decisions a Node test makes.

## Stores, not a query library

There is no react-query, swr, or zustand here.

A page holds its own reads in `useState`. A fact that genuinely spans screens -- who is signed in,
whether the rail is collapsed, which palette is painted -- is a module store from
`src/lib/store.ts`, read in a component through `useStore`. `store.ts` imports no React, so a
store is exercised in plain Node.

The rule that makes it work: a store publishes only when its value actually changed by `Object.is`,
and holds the reference it was given, so `useSyncExternalStore` sees a stable snapshot and does
not loop.

**A setting every screen spends is read by `lib/format`, not by every screen.** Which clock an
instant is rendered against is `lib/times`, and the formatters ask it -- so one setting moves every
timestamp in the app instead of each screen deciding for itself. Nothing under `src/pages` reads
that store, so the subscription is in `App.tsx`, on the route table: a change there builds every
route element afresh and the screen in front of somebody repaints. Subscribing in the shell would
not do it, because react-router hands the shell the same element object each time and React skips
a subtree whose element has not changed. `lib/preferences` is the same shape for a behaviour
rather than a rendering -- whether a log pane opens following the tail -- and the pane reads it
itself.

## A thing is titled by name and addressed by code

Every addressable thing the API answers with -- a pipeline, a connection, a schedule, a
webhook, an alert rule -- carries the same four fields, and the UI renders them the same way
everywhere: `id`, which nothing draws; `code`, the kebab-case key that appears in the URL and
in every document that references the thing; `name`, an optional human title with no identity
at all; and `description`, the long-form body.

**The title is the `name` when there is one and the `code` when there is not, and the code is
always on screen.** `lib/identity` is where that is decided, once: `titleOf` answers the
title, `headingOf` answers it with the code to draw in mono beneath it -- or with null, when
the title already is the code and wears the mono face itself. Every listing, panel header,
breadcrumb, graph node and palette row asks there rather than spelling `name ?? code` out
again, so no two screens can disagree about a name that is whitespace, the code is never drawn
twice, and the string somebody would paste into a URL or type into a document is in the same
place on every screen. A screen that showed only the name would be a screen nobody can act
from.

**A listing headed by titles is ordered by them.** The API answers a listing in code order, and a
screen that drew the names but kept the codes' order would read as no order at all -- so the
pipelines listing sorts by `titleOf`, without case, with the code breaking a tie. A run row is
headed the same way: `RunOut.pipeline` is a code and nothing else, so the runs screen reads the
pipeline names once and joins, and a code the read did not reach is still headed by its code.

**`description` renders as markdown, sanitised by construction rather than by filtering.**
`lib/markdown` uses `marked` for its lexer alone and answers a tree of blocks and inline runs;
`components/Markdown` turns that tree into React elements. No HTML string is ever produced, so
there is nothing for a sanitiser to clean and nothing `dangerouslySetInnerHTML` could be
handed -- a `<script>` in a description arrives as a token and leaves as text React escapes.
Paragraphs, headings, emphasis, inline code, code blocks, lists, quotes, tables and links are
the subset a description needs; anything else is drawn as the source it was written as, and a
link is followed only for `http`, `https` and `mailto`. A table is set the way its column
declared and scrolls inside its own box, because a description is drawn in a panel narrower than
some tables are. A listing row is the exception, because a
cell is a glance: `oneLine` closes up the whitespace and the row truncates the words rather
than rendering a heading cut in half.

A step is the one exception to the shape, and it is the same rule underneath. Its map key is
the reference -- what `depends_on` and `${steps....}` read -- so the key plays the part `code`
plays elsewhere, and the step's optional `name` is the title drawn above it.

## One way to say a time

**How long ago on screen, the exact instant on hover.** What somebody asks of a timestamp is how
recent it is, so `formatRelative` is the visible text everywhere -- in a listing cell, in a panel
fact, beside a version -- and the wall clock is the element's `title`. `components/Instant` is
that pair written once, and a screen that spelled a wall clock out where the listing beside it
said "2m ago" would be two answers to one question on two halves of the same screen.

**An exact instant is written largest field first**: `2026-09-02 11:36:05`, and ` UTC` after it
when `lib/times` is set to that clock. `formatInstant` is the only place it is spelled, and it is
not the reader's locale: an instant is read here to be compared -- against a log line, against
another screen, against what a machine wrote -- and `9/2/2026, 11:36:05 AM` sorts by nothing and
means two different days to two readers. A relative reading that has run past its recency window
falls back to the date half of the same spelling rather than to a locale date.

**Time speaks in both directions.** `formatRelative` measures either side of now -- `3m ago`
behind it, `in 3m` ahead of it -- through the same units and the same thirty-day horizon, past
which both fall to the date half of the exact spelling. When a schedule fires next is the same
question as when a run started, so a next fire time is an `Instant` like every other moment in
the app rather than a wall clock spelled out where the column beside it says "2m ago". The
window either side of now is one instant: a clock a few seconds out of step with the server's
reads as "just now" rather than as a firing already overdue.

**A schedule says what is true of it where the next firing would go.** Pausing keeps the
computed `next_fire_at` on the row -- resuming recomputes it from now, so it has to carry on
from somewhere -- and a paused schedule that drew that instant would promise a firing the
scheduler will not make. It says "paused" instead, muted, in the listing cell and in the panel
fact both; the chip beside its name is what a chip is for, and this is the answer to the
question the column asked. A schedule with no next instant at all says nothing is scheduled
rather than drawing a dash, and that reading comes first: a one-time schedule pauses itself
once its moment has gone by, so the flag alone would have a spent clock read as a stopped one.

**A window is the exception, and it is read exactly.** Every other instant on a run answers how
recent it is, so it wears the relative form; the interval a run covers is what a step filtered its
query on, and what somebody checks it against is a date on a source rather than the distance from
now. `formatWindow` is that pair -- both ends through `formatMoment` on the clock the app is set
to, the zone stated once after the two rather than on each -- with the instants as the wire wrote
them on the element's `title`.

**A box that takes a wall clock names the clock it is read against.** A rendered instant carries
its own suffix, so nothing beside it has to say which zone it is in; a `datetime-local` control
carries none at all, and what somebody types there is read against the app's own setting before it
is sent. So a section of them states that zone once, in mono beside its label, and each box says
nothing about itself. `lib/times` answers what it is called and how far from UTC it is at a given
instant, which is what turns a typed wall clock into ISO 8601 with a zone on it. What the
browser draws inside such a box is its own locale's spelling, and it is the one place in this app
an instant is not written largest field first: the control is the platform's, and a box drawn by
hand to spell it the house way would be a date picker this app then owns.

**A one-time schedule is a moment, and it is read like one.** Its `at` is drawn through
`Instant` -- "in 2h" before, "3d ago" after -- rather than as a raw clock string, and once it
has fired the cell says so in front of the instant. What decides that word is `last_fired_at`
and never the calendar: a moment that has passed with no firing behind it is one the scheduler
has yet to reach, and saying "fired" of it would be a second untruth in place of the first.

## A listing is a cursor walk

Every screen that draws a listing draws it with one component. `components/list/ListTable` is
the heading row, the striping, the row that reaches for the next page and the line along the
foot; a screen decides its columns and what each cell says, and nothing else. Where a row opens
something beside the table -- a connection's form, a trigger's history -- the screen passes
`onSelect`, and the row answers Enter and Space as well as a click, because a row only a pointer
can open is a row some people cannot.

**There are no page numbers, because this API has no pages.** Every listing is a keyset walk
answering rows and an opaque cursor, and no total -- so what the foot can honestly say is how
many rows have been read and whether there are more. `lib/paging` is what an answer does to the
rows already held, as pure functions over the state; `hooks/use-paged` is the part that needs a
browser, and it holds the question beside the rows so an answer to filters somebody has since
changed cannot land on the screen.

**A trigger row is two fixed lines.** The lead cell is `headingOf`'s pair -- the title, and the
code beneath it in mono only where the title is not already the code -- and everything else the
row has to say about itself goes on that second line as a chip: the document that owns it, or
`managed`, and `paused` or `disabled` where that is true. There is no kind chip, because the
heading over the table is the kind, and no id, because a row's key is not something a person
reads. A row whose height depended on how many chips it wore would make a listing of twenty rows
a listing of twenty heights.

`hooks/use-read` is the one-page sibling of `use-paged`, for a read that is a document rather than
a listing -- what this instance has installed, how the last day of runs came out. Same rule: the
read function's identity is the question, and an answer to a question nobody is asking any more is
discarded rather than left on screen.

**Nothing polls.** A run's own screen holds one event stream; a listing holds none, because a
page re-read every few seconds is load for a tab nobody may be looking at. A tab that comes back
into view re-reads page one once and puts what is new at the head, matched by id, so a row
already on screen is refreshed in place rather than moved -- and the count of what arrived is
what the pill on the runs screen offers.

**A filter is the server's or it is not offered.** `GET /runs` narrows by pipeline, by status,
by how far back to look and by the tags the run's pipeline wears, and those four are what the
runs screen has. A control for something the server cannot filter would narrow whichever rows
happen to have been loaded while appearing to answer the question it asks. Where a screen does
narrow what it has loaded -- finding a pipeline among the pages read so far -- the foot already
states how many rows those are.

**A tag filter is a set, and its members stand beside the control.** `tag` repeats on the wire
and repeating it narrows, so the control is a menu of checkboxes rather than a choice, and each
chosen tag stands next to it as a chip that removes itself. Where a row already draws its tags,
the chip on the row adds it to that set: the filter is reached from the thing that shows what to
reach for. Where a row's tags would be the same words repeated down a column -- every run of one
pipeline -- the rows carry none and only the filter does. On the pipelines screen the set lives
in the address (`?tag=`) so a narrowed listing is a link somebody sends, and it is replaced
rather than pushed, because a filter being assembled is one destination and not five. The runs
screen carries the same control beside its own three, seeded from the address once and held in
state after: a control that wrote every keystroke back would put a history entry behind each one.

**A tag on a row is the filter's own door.** `components/TagChip` is a chip until it is given
`onSelect`, and then it is a button saying "Filter by <tag>" that adds that tag to the set the
table is already narrowed by rather than replacing it. The pipelines table is where that lives,
because a tag drawn on a row somebody cannot press is a fact with a gesture missing from it.

**The lead column keeps half the table at every width.** A row's identity -- its title, its
code, its description -- is what somebody scans a listing for, so the first column is
`w-full max-w-0`, truncates with the whole value on hover, and carries a floor of half the
listing's width that nothing beside it may bid down. The Tags column takes at most a quarter,
and every other column on the row is shrink-to-content and says its piece on one line -- bounded
too, so a column whose own words would push the identity under its floor is cut with the whole
of it on hover rather than taking the room from the title.

**The tags fold to the room they have rather than wrapping into it.** Chips are one line: a row
whose height depends on how many words it wears makes a listing of twenty rows a listing of
twenty heights, so what does not fit that quarter folds into one trailing `+N` chip -- which
says how many it is holding, spells them on hover, and opens them as the same filter every
other chip on the row is a door to. A second line is allowed only where a table is 1280px or
wider, and never more than eight chips are drawn whatever the room. **The fold is computed, not
guessed**: a chip is mono at 12px, so how wide one is is arithmetic over its characters, and
`lib/tag-fold` fits the words -- the `+N` counted as the chip it is -- into the room one
`ResizeObserver` on the listing's own card measured. One observer for the listing rather than
one per row, and a share of the table rather than the cell's own width, which is the width the
chips already took. Below `lg` a row is a card and the tags have a row of their own, so nothing
folds there.

**A choice closes on its choice; a set stays open.** `components/list/Choice` is one value out of
a menu of them, and picking one shuts the menu, because the question has been answered. A set is
the other case: several tags mean AND, so `TagFilter`'s rows are checkboxes and the menu stays
where it is until somebody is done with it. Neither trigger wears a count -- what has been chosen
stands beside the control as chips that take themselves off.

**A count says what it counts.** `rowsRead` writes "1 pipeline", "50 runs, more to load": the noun
is the row's, singular where there is one of it, and a listing with a cursor left says so. A bare
number along a foot reads as a total, and a keyset walk has no total to state.

A dependency one screen needs is fetched when it is needed, and that is not always a whole lazy
route. The YAML parser the apply dialog needs is an `await import('yaml')` inside the handler
that sends a document, so a reader who never applies one never downloads it, and the editor it
writes the document in arrives the same way.

**A document is written in one editor wherever it is written.** The dialog on the listing takes a
whole `dirigent/v1` document, which is the same thing the source pane holds, so it holds the same
Monaco against the same `GET /schema/document` -- a key no block takes is squiggled where it was
typed rather than reported a round trip later. Each pane names its own buffer, because monaco
holds one model per uri and two panes sharing a name would share a document.

## A graph is a shape, and each screen reduces its own to it

`lib/dag-layout` knows nothing about runs or documents. A run's graph is its pinned definition
with a state on each node; the editor's is the stored document with an edit mark on each. The
geometry of the two is one problem, so what elk is handed is an id and a height per node and a
pair per edge, and each screen reduces its own shape to that. `components/graph` is where React
Flow and elk are actually imported -- the canvas with this app's props on it, and the hook that
asks elk for positions -- and both graph components are lazy, so the two of them share one async
chunk rather than shipping two copies.

**Motion lives on edges, and it means data travelling.** A run's graph is the one place in this
app that moves, and only while the run is live: an edge out of a step that has produced its output
into one still reading it is dashed in the identity amber and travels along its path, and the
moment a step produces its output every edge out of it into a step that could still read it plays
one short handover before settling. An edge stills as soon as either end is done -- a source that
failed or skipped never had an output to send, and a target that has settled is not reading one.
A node gains nothing from any of it -- status colours stay the only colour voice
there, and selection stays neutral -- so what a reader watches is where the data is, not which box
is loud. A terminal run is still everywhere, and so is one opened after it settled. Somebody who
has asked their machine for less motion gets the same reading standing still: a travelling edge is
lit in the same amber and a handover is not drawn at all, decided in `lib/run-detail` from the
setting rather than left to a stylesheet to hide -- and the stylesheet stops the animations as
well, so a frame rendered before the preference lands is still still.

**Layout is recomputed on the shape, not on the state.** `signatureOf` is what the elk call is
keyed on: which nodes there are, how tall each is, and what joins them. A step going from running
to succeeded moves nothing, and neither does typing into a config field.

## A form is a JSON Schema, read once

`lib/schema-form` turns a JSON Schema into field descriptors: which control a field takes, what
its bounds are, whether it is required, what its enum offers. A block's config schema and a
pipeline's parameter schema are both fed through it, so the step form and the run dialog are one
decision rendered twice, and every shape the shipped catalog publishes has a test.

**What no control fits is edited as JSON.** A list, a map, and a schema with no type at all are a
textarea rather than a wrong control -- guessing at a list of integers with a text box is how a
document ends up carrying `"[200]"`. The fallback has a test of its own, so a shape this bundle
was built before degrades rather than misleads.

**A field that carries a program is edited as one.** A string whose schema published a
`contentMediaType` -- `application/jq` for the three jq verbs, `text/x-shellscript` for the shell
string `shell.run` and `docker.run` take -- gets the same Monaco a document is written in, through
the same `CodePane`, so a jq program is read on the lines it was written on. The schema is what
decides this and nothing else: every other string stays one line, however long a value it holds.

**The label is the key.** What is being edited is a document, and the word an author writes in it
is `max_response` rather than "Max Response". `description` is the help under the label, and whether a
field is required is said beside the label rather than inside it, so the control's accessible
name stays the key.

**Every field is a design-system control, and an empty one looks like an empty one.** A field
renders through `ui/input`, `ui/textarea`, `ui/select` or `ui/switch` and never a bare element,
and the treatment is checked in both palettes: the dark one fills a rung of the ladder and edges
it with a hairline the ground shows, and the light one has to say the same thing with a fill and
a stronger line, or a value floats in whitespace and an empty box is not there at all. A row is
the key as its label, the annotation beside it, the control, and one muted line under. An unset
secret is an empty password box with a placeholder saying so -- never the words "not set" as
prose where a control belongs.

**A section the document requires is open, and one it does not is a link.** A run dialog asks for
a window because the document it runs reads one -- a step writing `${run.window.start}` stops the
run it is given none in -- so where the document references it the section stands open, every field
in it is required, and the verb is shut with the sentence saying what is missing. Where the document
references none, the same fields sit behind one plain link and nothing is asked. A dialog that hid a
field the document cannot run without would have the server refuse what the form could have asked
for; one that opened every optional section would make every dialog the longest form it could ever
be.

**The refusal here is the client's half.** A field is checked against its own schema so a form can
say what is wrong before it asks. Whether a document applies -- its graph, its references, the
blocks it names -- is the server's, and the editor's Validate and Apply are the same dry run
asking it.

## The pipeline editor edits a copy

A pipeline is a chain of immutable versions and the only verb that changes one is `$apply`, so
the editor holds a local document in `lib/pipeline-document`: the graph, the step form and the
source pane are three readings of it, and the count of unapplied edits is the difference between
it and the version the instance holds. It is a module store because those three are not inside
one another.

**A pipeline that does not exist yet is edited in the same screen.** `/pipelines/new` is the
editor with no pipeline behind it: the local document is a skeleton nothing has applied, so
everything in it is editable, the code among it. Validate is the same dry run against the draft;
Run is shut, because `$run` runs the version the instance holds and there is not one. The first
apply creates the pipeline and the screen goes to the address it will answer at from then on --
which is why a static `pipelines/new` route sits beside the dynamic `pipelines/:code`, and why the
button that opens it is the primary one on the listing while the apply dialog, which is the door
for a document written somewhere else, is the quiet one beside it.

**A document opens on the source that holds it.** The editor's panel opens on the step tab,
because a pipeline is read a step at a time, and choosing a box on the canvas opens that tab
rather than whichever one was last in front of somebody. The exception is a document that arrived
as text: `From file...` on the listing hands the editor what it read, and the editor opens on the
source pane, which is where that document actually is. A blank `/pipelines/$new` opens on the step
tab like every other screen -- the canvas says how to add the first step, and the source, whose
schema would mark an empty `steps` map before anything had been done, is a tab away.

**Apply is quiet until it would write.** The button takes the identity colour where the document
differs from the version the instance holds, and where there is no version at all; where applying
would write nothing it stands in outline beside Validate, which is what it would do.

**The source pane may hold text that is not a document**, and while it does, the local document is
the last one that parsed and nothing else may write to it. A form quietly replacing text somebody
is halfway through fixing is worse than a form that says it cannot.

**The YAML in the source pane is rendered here, not served.** `GET /pipelines/{code}/$export` is
the canonical text: it orders steps topologically and keys the way a digest is taken over. The
pane renders the local document as it stands, in the order it is held in, so what is edited and
what is read back are the same thing -- which means the text can differ from a later `$export` of
the same document in key order and in nothing else. An apply canonicalises it.

**The editor's schema comes from the instance.** `GET /schema/document` answers with
`dirigent/v1` composed with this instance's own block config schemas, one `if`/`then` case per
installed block, so monaco-yaml marks a config key the named block does not take at the character
it was typed at. An instance with a plugin another lacks answers with a different schema, which is
the point: the editor refuses exactly what that instance's apply would.

## The palette is a registry

`src/lib/palette.ts` holds actions as data: `id`, `title`, `group`, `keywords`, `hint`, `run`.

The shell registers what is always there -- every screen the account is offered, the view rows,
sign out. A screen registers what only it can do, from an effect, and returns the unregister so a
row cannot outlive the screen that would carry it out. Re-registering an id replaces the row.

The settings dialog is the same idea for a different surface: `src/lib/settings.ts` holds every row
as a record -- what it is called, which category it is filed under, what else it can be found by --
so its search box is one pure function across every category rather than a traversal of markup, and
the shortcut rows are derived from `lib/shortcuts` rather than written down twice. What a row puts
on its right edge is the dialog's, keyed by the row's id.

**Its nav reads Preferences, You, This instance**: General, Theme and Shortcuts are preferences,
Account is the reader's, and Server is the instance's. There is no About, because a version stated
on two panes of one dialog is the same fact twice; the documentation and the API reference are two
links at the foot of the Server pane, where the instance they answer for is. **No pane carries a
line under its heading and almost no row carries one under its label.** A row's `description` is
optional and survives only by adding a fact the control cannot show, such as which timestamps a
clock setting moves and which keep their own -- so a line restating the label is not written.

`filterActions` is a pure function and cmdk's own scoring is turned off, because cmdk ranks by
fuzzy match over rendered text and would put a screen's own name below whichever row shares more
letters with the query. Every term must match, so typing more words narrows; a title that starts
with the query sorts above one that merely contains it.

**Every chord this app binds is a letter.** On a Norwegian layout `[`, `]`, `{`, `}`, `|` and `\`
all need Alt to reach at all, so a binding over one of them is a binding nobody here can press.
Cmd/Ctrl+K opens the palette, the platform's own modifier plus B folds the rail, `T` shows and
hides a run's terminal, and `?` opens the list of every key -- each matched as the character it
produced, never as Shift plus a physical key.
`src/lib/shortcuts.ts` decides every press as a pure function; `hooks/use-app-shortcuts.ts` is the
one place a real `KeyboardEvent` is read.

## Panels are sized in pixels

The rail has two widths and nothing between them: 200px with labels, 56px of icons with the labels
back as tooltips. It is not draggable -- a rail's width is a property of its longest label rather
than of the work in front of somebody.

**What is in the right panel is the screen's.** The panel itself is drawn once, in
`components/RightPanel`, and a screen fills it with `fillPanel` from an effect that returns the
unregister -- the same shape as registering palette actions, and for the same reason: a panel
cannot outlive the screen whose data it is drawing. A tab is an id, a label and a `render`, and
the open tab is remembered by id, so a screen that gains a tab does not move the reader onto a
different one. A screen that fills nothing gets the line saying so.

**The status bar is the shell's; the two facts on it are the screen's.** `lib/screen-status`
holds one note and one identifier, stated for as long as a screen is mounted -- where a run's
event stream is, and the trace the run is on. The note is data with a tone rather than markup, so
what a connecting stream says is a pure function and the bar stays one row whatever it holds.

The right panel is dragged, and what is stored is **pixels, not a fraction**. What somebody
dragged it to was a decision about the content in it -- wide enough for a log line, narrow enough
to leave the table readable -- and a fraction re-decides that every time the window is resized. A
window narrower than the stored width clamps for that session and leaves the stored number alone,
so the intent comes back with the window. The drag handle is a `separator` and answers the arrow
keys, because a panel that can only be sized by pointer is a panel some people cannot size.

**One hook drags all three edges.** The rail's right edge, the right panel's left edge and the run
terminal's top edge are the same three sentences with a different coordinate read off the pointer,
so `hooks/use-drag-size` takes the axis as a parameter rather than being copied per direction.
The pointer is followed on the document rather than on the handle, and the size is written to the
element's own style while the drag lasts -- a React render per pointer event leaves the edge
visibly behind the hand -- with the store hearing one committed number on release.

## The shell has two rules, and each is one line

Rail, content and right panel meet in a strip along the top and a bar along the foot. **Every
strip in a row is the same height** -- `h-shell-top`, `h-shell-foot`, stated once in `index.css`
-- **and the rule between the strip and the work is drawn once**, never once per column: the
top rule is a single full-width element the shell owns, and the foot is a single full-width bar
with two cells inside it, the settings cell tracking the rail's own width store. Two elements
each drawing half a border is a line that comes apart at a column edge, and the bottom of the
app then reads as a step. `e2e/shell.spec.ts` measures every strip with
`getBoundingClientRect`, in both palettes, with the rail collapsed and the panel open.

**A fact appears once in the shell.** The instance's name, environment and version belong to
the corner identity and the health popover behind it; the status bar carries the screen's own
two facts and the account, and never repeats them. What a screen states there is what nothing
else on it already says -- how many rows were read is the foot of the table's line, not the
bar's -- and an instant is the house's relative form rather than a locale string.

**Settings lives at the bottom of the rail's column**, in that bar; the instance's identity --
a dot, its name and environment from `/system/info`, its version -- lives at the right of the
topbar, and opens the health popover. The rail's own entries are **single-line labels**: what
this app is made of is Pipelines, Runs, Schedules, Connections and Blocks, and a word that names
one of those needs no gloss under it. The line each entry carries about itself is data on the
entry, and the command palette is where it is read.

## Small screens

The shell has one breakpoint, `md` at 768px, and one rule above it: at `md` and up nothing about
the shell on this page changes. Everything below is what the same screens become on a phone.
**Nothing scrolls sideways.** A page whose body scrolls horizontally is a defect, whatever is in
it.

**A table has a second breakpoint, `lg` at 1024px, and the width is why.** At 768 the content
column is what is left of the window after a 240px rail and the page's own padding -- about
500px -- which is a phone's width with a rail in front of it, and a listing of four or five
columns drawn into it puts a tag chip over the title beside it. So a listing takes the card
form below `lg` while every other rule on this page turns at `md`, and `useNarrowTable` is that
question rather than `useSmallScreen`.

**A utility hides; `useSmallScreen` chooses.** `md:hidden` on one of two renderings leaves both
in the document -- every row and every control twice, two elements with one accessible name --
so where the same content is drawn two ways, the hook is what decides and only one is built. A
class is still the answer for hiding a thing that has no second form.

**The rail becomes a drawer.** Below `md` it is off screen until a menu button at the left of
the top strip -- icon only, `aria-label` "Open navigation" -- opens it over a scrim. It closes
by its own close button, by Escape, by a tap on the scrim, and on every route change, because a
drawer still standing over the screen somebody navigated to is a drawer they have to dismiss
twice. Focus moves into it on open and back to the button on close. Settings lives at its foot,
where the rail's own cell in the status bar puts it above the breakpoint.

**A listing row becomes a card below `lg`.** The table is one component and so is its small
form: `ListTable` draws its first column as the card's head -- the title as the row's link, the code
in mono once -- and every other column as a labelled fact under it, labelled by that column's
own header. A column with nothing in it for that row is left out of the card rather than drawn
as an empty label. What a row does above the breakpoint it does here: a row that opens a panel
opens it, and a row that is a link is one. The card is the whole listing's form, header row and
column widths included, so nothing on a narrow table has to be told how to shrink.

**The breadcrumb shows its leaf**, and the crumb carrying the thing's code where the leaf is not
it -- the code is on screen on every screen. The whole trail is the element's `title`; the leaf
truncates with an ellipsis rather than wrapping the strip onto a second line.

**A toolbar does not wrap, here or anywhere.** A screen's verbs are data rather than markup --
`ToolbarActions` -- so that below `md` the primary action can stay on the strip while everything
beside it moves into one overflow menu, `aria-label` "More actions", without a label being
written down twice.

**A dialog is a sheet.** Full width, full height, its footer pinned to the foot and its body the
part that scrolls. It is the generated dialog's own slots that are restyled in `index.css`, not
a second dialog.

**The right panel opens from the foot.** Below `md` it is a full-height sheet over the screen,
raised from a tab bar across the bottom carrying the tabs the screen filled -- so the graph
screens are the graph, and what is beside them is a tap away. A screen that fills no panel has
no tab bar.

**A document is read, not written, below `md`.** The source pane is read-only, the add-step and
delete-step controls are not drawn, and neither is any of the three verbs -- Apply, Run, and the
Validate that would dry-run a document nothing here can change. The strip says "Read only on a
small screen" where the verbs were, and carries the document's identity and nothing else: what
version it is at is along the foot already, and a fact appears once on a screen. A graph is still
read, a step is still chosen, and a run is still watched.

**Every control a finger lands on is at least 40px tall.** That is a variant on the shared
control classes in `index.css`, against the generated primitives' slots, so a screen never
sizes a button for a phone itself.

## An option wears what its value wears

A dropdown whose options are values the app already draws somewhere -- a status, a kind --
renders each option as that drawing: the status filter's rows are the same chips the listing
shows, and the trigger carries the chip it chose. Choosing becomes recognising. An option
never wraps; the menu grows to its longest row instead of folding a label in half.

**A choice between looks is made on the looks themselves.** Where the values of a setting are
appearances -- the three palettes -- the control is one card per value showing that value, and
the card is the radio: `role="radio"` inside a `radiogroup`, one tab stop for the group, the
arrows moving and choosing in one gesture, Space and Enter choosing what has focus, and a two
pixel accent ring on the chosen card and on the focused one. The chosen card also carries a check
in the accent, because a ring alone is a colour doing a mark's job. A swatch is drawn from the
tokens it stands for and never from a colour written down beside it.

## A row expands under itself rather than opening a second dialog

Where a row's verb needs a form -- changing a password on the settings dialog -- the form opens
in that row's own place, under it: its fields on one line, and Cancel beside the verb, right
aligned at its foot. A dialog raised over a dialog puts a scrim over the thing it is about, and
the row that offered the verb is already the sentence saying what the form is for. The button
that opened it is replaced by the section while it stands, so there are never two controls that
shut it, and the refusal is `Refusal` inside the section, where the fields it is about are.

## A write that can be refused says so, and a shut control says why

**Every write states its refusal, and there are two places to state one.** A dialog or a form
has room beside the thing that was refused, and that is `components/Refusal`; a row's button and
a panel's verb have none, and that is `sayRefusal`, the one toast this app raises about a
request. A write whose rejection handler is a comment saying the row keeps what it had is a
write that failed in silence. **Nothing dismisses on a refusal**: a dialog that closed and a
panel that emptied would both have said the request went through.

**The refusal is read from the problem document, not from the status.** `Problem.title` is the
status phrase this server sets it to, so a dialog headed by it says "Unprocessable Content" on
every refusal it can make; what a person acts on is `detail`, and `problems` is the list behind
it. `lib/refusal` is where that is decided once -- including that a `detail` which is only its
own `problems` joined is drawn as the list alone rather than as the same sentence twice.

**A control an account's role would have refused is shut, with the sentence saying why.** The
API has two role gates and so does `lib/roles`: an operator applies, runs and schedules, and
connections, schemas, accounts and tokens are an admin's. `useMayWrite` is what a control asks,
and it is the only reader of the role, so no screen can have its own idea of what a viewer may
press. This is the same courtesy the rail's admin section is -- the server is what refuses -- and
what it buys is nobody pressing a button to be told off. A disabled control takes no pointer
events, so the sentence goes on `components/Refusable` around it as well as on the control.

**A required field is not a complaint until somebody has been there.** A form marks and states a
problem only for fields that have been left or that a submit asked about; the button the caller
owns is what stays shut in the meantime, saying why. A box drawn red the instant a dialog opens
is telling somebody off for opening it.

## Nothing wears interactive chrome unless it does something

A row lights under the pointer whether or not it can be opened -- `.row-hover`, one wash from
the surface ladder, weaker than anything meaning chosen, spanning the row's full width the way a
menu item's does. The cursor is left alone on a row that opens nothing: a pointer finger is a
promise. A panel nobody has filled has no tabs, so its strip carries a plain label rather than
one lone tab shaped like a control. A button that takes something away -- revoke, deactivate,
cancel -- wears `.destructive-action`, which tints critical on hover and says what the click
costs.

**Where a stock behaviour exists, it is the behaviour.** A menu that marks a choice puts the
mark in a reserved gutter on the left, in the same column on every row, and hangs off its own
trigger. The generated files in `src/components/ui/` are pristine, so what this app wants of
them is said in `index.css` against their slots, never by editing them.

## A graph fits what it draws

**An editor node is two lines and a run node is three.** A document's node is the step's title
-- its `name` if it has one, its map key otherwise -- and the block it runs; its config is a
map of any size and one truncated line of it crowds the box without answering anything, so the
step's own pane holds the whole of it. A step whose `for_each` fans it out says so on its mono
line -- a stacked glyph and the count, or the word "each" where the list is an expression a run
resolves -- in the neutral ink that line is already in, because a status is the only colour a node
carries. A run's third
line is live state -- what a step is waiting for, how a retry went -- and stays. Elk is told
the height each is actually drawn at, or the rows come out spaced for a box that is not there.


Both canvases open with the whole DAG in view: `fitView` with padding, held between the two
bounds in `lib/dag-layout`. `FIT_MAX_ZOOM` keeps a pipeline of two boxes at its own size rather
than magnified to fill the space, and `FIT_MIN_ZOOM` keeps a node above the size its 14px title
stops being readable at -- a graph too big for that is panned to rather than shrunk past
legibility. It re-fits when the node set changes and when the canvas is resized, and stops the
moment the reader pans, zooms or drags a box -- after that the view is theirs, and Re-layout is
how they hand it back. The browser suite asserts every node's box lies inside the canvas.

**A deep graph is wrapped onto rows rather than drawn as one.** Seventeen steps in one
left-to-right row is three thousand pixels of canvas, and a fit answers that by putting a node's
text under six pixels. Past `WRAP_WIDTH` -- which `rankDepth` measures a shape against before elk
sees it -- elk is asked to cut the layering into chunks and stack them: the ranks still read left
to right, and the height nothing was using carries the rest.

**The zoom controls are this app's.** React Flow's own step by a fixed twenty percent, which on a
graph read at half size is four presses to nothing, and its fit button fits with the library's
options rather than the ones both canvases share. `ZOOM_STEP` is one press either way, and the
fit button is `fitCapped`, the same one every other fit goes through.

## The canvas edits

**One canvas, two modes.** `GraphCanvas` is a view until it is handed `editing`, and then it is
an editor: draw an edge, delete one, move a box, finish moving it, drop a connection on empty
ground. The run's graph passes nothing and is what it was -- a step is selectable there and
nothing else, because what it draws already happened and no verb would change it. The same
split is on the box itself: `StepPorts` draws the two anchors React Flow routes an edge to, and
only the editable mode makes them ports -- visible, connectable, `.dg-port` in index.css. A
run's graph keeps the anchors and shows none, and the browser suite asserts that.

**An edge is a `depends_on` entry, and it is one edit however it was made.** Dragging between
two ports and choosing a step from the chips in its own pane end in the same `withDependsOn`
against the same local document, so the topbar counts a drawn edge with everything else
unapplied and nothing is written until an apply. `lib/graph-edits` is that seam: `withEdge` and
`withoutEdge` answer with the document they were given when it already says what was asked, so
drawing an edge twice is a gesture rather than an edit. A selected edge and the Delete key take
one away, and so does a selected step -- `withoutStep` takes its name out of every other step's
`depends_on` in the same edit, because a `depends_on` naming a step the document no longer
declares is what an apply refuses. Only one thing on the canvas is chosen at a time, or one press
of the key would take two away. React Flow answers neither key while the focus is in a text box,
so a Backspace meant for a config field is never a step.

**A loop is refused before it is drawn, and the refusal names it.** `cycleThrough` walks the
document's own edges and answers the shortest loop the new edge would close -- `parse → active →
report → parse` -- which is what the toast says. `$apply` refuses the same document; a canvas
that accepted the gesture would have answered a pointer with a round trip.

**elk places a graph; a reader places a box.** A dragged position is that pipeline's own, kept
in `lib/canvas-layout` under `dirigent.layout.{pipeline}` as px-intent, exactly as the right
panel's width is -- what somebody dragged a box to was a decision about that pipeline's shape,
and it survives a reload. A step nobody has moved keeps elk's suggestion, which is what a step
added to an arranged canvas gets. Re-layout clears the arrangement and fits the view to what elk
decides afresh.

**A step is added from one menu, wherever the asking started.** A right-click on empty ground
opens it at the pointer -- on a document with no steps as much as on a drawn one -- the button
in the corner opens the same menu under itself, and a connection let go over empty ground is
"and then this": it opens where it was dropped, says which step the new one will wait for, and
the step lands there. A right-click on a box opens that box's own menu instead: one more step
after this one, which is the same add-step menu with the edge already decided, and this one
taken out.

**The menu is shelved the way the catalog is, and searched the way the palette is.** The rows
are the groups the blocks themselves declare, which is what the Blocks screen shelves by, so the
menu invents no filing of its own and `map.jq` and `transform.jq` land on one shelf. A sensor sits
in its group like anything else and wears the chip saying it waits, because a chip on every row
would say what the absence of one already says. Typing replaces the shelves with flat breadcrumbed
results -- `shell ▸ run` -- every term narrowing, `sensor` and `operator` matching by kind; the
arrows walk them and the return key places one. The first Escape clears the box and the second
closes the menu. `lib/add-step` is all of that as pure functions, so what the shelves hold and
what a search finds are decided in Node.

**The key is derived, not asked for.** A menu that places a step on one keystroke cannot stop
to ask what to call it, so `transform.jq` lands as `jq` and the next one as `jq_2`, and the
step's own pane is where it is renamed -- alongside everything else about it.

## The run screen

**A run is named by when it started.** A run has no name of its own and its id is a handle for
machines, so what heads one is its pipeline's code and the instant it began, spelled the house way
and with the id on hover. `Run` is the word that stands in over the pipeline's name until there is
a run loaded to name -- the palette's shelf while the read is in flight -- and it is followed by
the pipeline and the instant the moment there is one. A queued run has not started, so every one
of those readings takes `started_at ?? created_at` and none of them can draw a blank.

**Two durations, measured at two altitudes.** The run's is `started_at` to `finished_at`, beside
its status chip; a step's is the earliest start of any of its attempts to the latest finish of any
of them, drawn at the far end of its node and again as the step's `took`. They are not one number
seen twice, and the step's is a bound rather than a first and a last: a fan-out's elements settle
out of arrival order, so what the stream said first is not what the step began with. A running
step counts against the screen's own one-second tick, which only exists while the run is unsettled,
and a duration with an end missing reads `--` rather than a number that would keep climbing after
nothing was happening. `formatDuration` is the one ladder -- `840ms`, `9.4s`, `42s`, `2m 4s`,
`1h 12m` -- and a decimal survives only under ten seconds.

**A step is titled by the quartet's rule and its block sits under it.** The first line is the
step's `name` where it has one and its map key otherwise, wearing the mono face when the title is
the key; the second is the block the step runs, with the key in front of it and a middot between
where the title was a name. So the key is on screen exactly once, whichever way round the step was
written, and what a step actually runs is never a click away. The third line is what the step is
doing -- what it is waiting on, what it saved to, what went wrong -- and the panel says the same
things as facts rather than as a second sentence.

## The terminal drawer

A run's screen stacks: the canvas above, and a console across the foot of the content area at
the height somebody dragged it to. The right panel is beside both and is untouched by either --
what is beside a run is a different question from what is under it. It is opened from a glyph in
the run screen's own strip, from a row in the palette, and by pressing `T`, which is a bare
letter because every chord this app has is already spoken for.

**The lines are the run's own state, not a second read.** `runs/{id}/$events` already carries
every line the run wrote; the drawer filters what the reducer holds, opens no connection of its
own, and never will -- `run-stream.test.ts` drives the whole of the drawer's data path through
`follow` and asserts the concurrent-connection counter still says one.

**Every step interleaved, in arrival order.** What happened to a run is a sequence, so the
console is one, and the step select is there for whoever is asking the other question. Each line
is time, level, the step as a clickable prefix, the message, and whatever fields the line carried
rendered muted after it. The prefix opens that step in the panel through `openPanelTab`, because
somebody clicking one is not asking for whichever tab they last had open.

**It is dark in both palettes, and it is the only thing in this app that is.** A console is not a
card -- it is a code block's cousin -- so the six `--terminal-*` inks are declared once and the
dark palette leaves them alone. The ground alone has two depths: graphite on the light palette,
where black reads as a hole in the page, and a rung below the dark palette's own background,
where the drawer has to read as deeper than the app. Its header strip is ordinary app chrome on
the surface ladder, which is what keeps every control in it a design-system control with
nothing re-inked.

**Three filters compose, and the count says how far.** A level threshold, one step, and a match
over the line are three predicates over one list; a foot line says "{shown} of {total} lines".
Client-side narrowing here is not the listing rule being broken: a listing's filter must be the
server's because a listing is a window onto rows nobody has read, and this is the opposite case.

**Copy takes what is on screen and download takes everything.** `$logs` answers a page of JSON
with no content-disposition, so the download walks the cursor through `apiFetch` and writes the
NDJSON out of a blob rather than pointing an anchor at a path that would navigate to a listing.

Open, dragged height, and the tail-following preference are all held the way the panels are:
pixels rather than a fraction, under `dirigent.terminal*`, with the drag on a `separator` that
answers the arrow keys.

## Every screen teaches

A page is a title, and a section heading is a heading. **An empty state states the fact** --
"No runs." -- and adds a second plain sentence only where the way in is not on the screen, such
as a document key or a CLI verb. A listing carries an `API` chip linking `/docs#/<tag>`, the fragment Swagger UI writes
on its own tag headings, so the requests behind a screen are one click away. Every screen states
its own two facts along the foot through `lib/screen-status`, including the ones that are still
stubs.

## The palette's anatomy

A 760px card at 15% from the top: a search row, shelved rows, a footer of key chips. **The
screen's own shelf leads** -- `shelve` in `lib/palette` puts every shelf whose rows claim
`screen` first, and the heading is free to name what it is scoped to, such as the run being
read. **A row is an icon tile and a title, nothing else.** What an action says about itself
(`hint`) feeds the filter and is never drawn: beside every title it is a column of glosses
saying what the titles already say. A row with no icon gets the neutral glyph rather than a
gap. **The filter is `filterActions`, not cmdk's** --
cmdk's own scoring is off, because it ranks by fuzzy match over rendered text and would put a
screen's name below whichever row shares more letters with the query.

## Adding a screen

1. A component under `src/pages/`, built on `PageState` -- loading, refused, empty, content, four
   states that stay distinct all the way to the screen. Collapsing "refused" into "empty" is how
   an instance whose database is unreachable gets told it has no pipelines.
2. A `<Route>` in `src/App.tsx`, inside the `AppShell` route.
3. An entry in `NAV` in `src/lib/nav.ts`. The rail draws that array and the command palette offers
   every entry in it, so nothing else has to be told the screen exists. An admin-only screen goes
   in the section whose `requires` is `admin` -- which hides it, and hides nothing from the server,
   because role gating here is a courtesy rather than a control.
4. Anything the screen alone can do, registered with `registerActions` from an effect that returns
   the unregister.
5. If the screen has something to show beside itself, `fillPanel` from an effect; if it has one
   thing to say about what it is doing, `setScreenStatus`. Both are undone the same way.
6. If it needs a dependency no other screen needs, a lazy route rather than an import.

A test asserts on a lib function, never on rendered markup. What is worth testing is the wire
layer and the pure decisions -- the fetch choke point, the SSE parser, the palette's filter, the
shortcut rules -- and all of it runs in Node with no DOM. Rendering is the browser suite's job,
and that suite drives a real `dg dev` rather than a mock.

## Interface copy is plain, and most of it is absent

A label, a hint, a description in the interface is plain product English: "Timezone",
"Follow logs", "Change your password." The house voice -- the wry sentence, the deliberate
turn of phrase -- belongs in this documentation and in commit messages, never in the words a
person reads while working. If a native speaker would not put it on a settings row, it does
not go on a settings row.

**The context says most of it; a sentence survives only by adding a fact.** Concretely:

- A screen carries no subtitle. "Pipelines" needs no line saying it lists the pipelines.
- The status bar's note exists only when it is stateful -- the editor's shape and warnings,
  the run's settled tone, the workers' health. A static note restating the screen is noise.
- A section heading over a headed table carries no gloss; the headers name the columns.
- An empty state states the fact and stops, naming a way in only when that way is not on
  the screen.
- A dialog's description earns its lines by teaching semantics the controls cannot show
  (what sealing a secret means), never by describing the dialog.

**A copy defect is a pattern, not an instance.** Fixing one gibberish line means sweeping
every screen for the same pattern in the same change -- the ui-review skill says the same.

**The door greets, and its eyebrow is the one line of text in the app set in the accent.** It is
the body size, uppercase and tracked out, in `--primary-ink`: the door is the one screen with
nothing on it to act on but the button beneath it, so the colour that means action is free to
name the product there. The login screen alone carries that eyebrow, a heading, a one-line subtitle,
placeholders and leading field icons, because it is the one screen a person meets before the
product's own facts are on it: there is no data to read, no title to take a heading from and no
shell around it, so the screen has to say where somebody has arrived and what to do next. No
other screen may copy any of it -- an eyebrow over a page title, a subtitle under a heading, a
placeholder repeating a label, or an icon inside a field is a defect everywhere behind this
door.

**The brand pane never carries a tagline.** What is on it is the mark, the word `dirigent`, and
the instance and the version the door answers for. A line saying what the product is for is
marketing on the one screen whose only question is who is asking, and the graph behind the lockup
already says what is through the door.


- A list's column header is sticky: rows scroll beneath it inside the list's own scroll container, and the header keeps the card background so rows never show through.

## Create actions

- On a screen whose heading names the noun, the primary create button says `New` alone --
  the screen supplies the object. The full name stays on the control's `aria-label`, on the
  palette action (global scope needs the noun), and on whatever the button opens.
- The one exception is a screen offering more than one create -- Users and tokens, Triggers --
  where each button keeps its noun, because `New` alone would not say which.
- An empty state states the fact and stops. It names a way in only when that way is not on
  the screen -- a document key, a CLI verb -- and never narrates a visible button: what New
  does is what New says.

