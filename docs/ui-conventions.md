# UI conventions

The web UI is a single-page bundle served by the API server itself, from
`packages/dirigent-server/frontend`. This page is authoritative for how it is built; where the
code disagrees with this document, one of the two is a bug.

Nothing here is about what the screens show. That is decided per screen, from a design board,
and each one arrives as its own change. What follows is the frame every screen is built inside.

**Every UI change is walked against this page in the live browser before its PR merges**, which
is what the `ui-review` skill does. Build the branch first -- `make ui-static`, because a checkout's
`dg dev` serves the packaged bundle where there is one -- then open every screen the diff touches
in the dark mode and again in the light one, at 390x844 as well as at a desk width: the finger
rule, a listing's card form and the panel sheet exist only below the breakpoint. Screenshots go
under `.playwright-mcp/review/`, which is never committed, and the PR body says the pass ran and
what it changed. A change to a token is read in all three palettes. A convention that proves
wrong is changed on this page first and in the code second.

## The stack

| Piece | What | Why it and not the obvious alternative |
| --- | --- | --- |
| Build | vite 8, TypeScript 7 with project references | `tsc -b` gates the build, because vite strips types without checking them |
| UI | React 19, react-router 7 with `BrowserRouter` | The server answers a navigation nothing claimed with the shell, so paths stay clean and a deep link can be pasted |
| Styling | Tailwind v4, CSS-first, entered through sokkel-ui's `styles-base.css` | There is no `tailwind.config.js` and there must not be one. The tokens, themes, fonts and base styles are [sokkel-ui](https://github.com/winterop-com/sokkel-ui)'s; `src/index.css` imports them, one `sources/<module>.css` line per library module the app imports, and then this app's own CSS |
| Components | sokkel-ui's primitives, shadcn `base-nova` on **Base UI** (`@base-ui/react`) | Imported from `@winterop-com/sokkel-ui/primitives/*`. A primitive that needs an option dirigent lacks gets it in sokkel-ui |
| Graphs | `@xyflow/react` for the canvas, `elkjs` for the layout | React Flow draws what it is given and decides no geometry; elk's layered algorithm is what places a DAG. React Flow rides in the graph screens' chunk and elk is a chunk of its own, in a worker -- see below |
| Editor | sokkel-ui's `CodeEditor`, on CodeMirror 6 | A pipeline document is YAML checked against a schema as it is typed, and the library's editor checks and completes JSON and YAML against JSON Schema 2020-12 itself, with ajv. Its own lazy chunk, behind `CodePane`, which is what every screen that writes source mounts -- a document, a schema, and a config field whose schema says it carries a program |
| YAML | `yaml` | A document crosses the wire as JSON and is written by people as text, and `lib/pipeline-document` is the one place it is parsed and rendered. Nothing in the entry chunk reaches that module, so the parser rides in the chunks of the screens that read a document |
| Markdown | `marked`, for its lexer only | A description is authored markdown and has to render as prose. Nothing here produces an HTML string, so what is drawn is a token tree React escapes -- see `lib/markdown` |
| Palette | cmdk | |
| Toasts | sonner | |
| Mode and palette | sokkel-ui's appearance: `useAppearance`, `useScheme`, and its `appearance.js` before the first paint | |
| Fonts | IBM Plex Sans and IBM Plex Mono, self-hosted through `@fontsource`, which sokkel-ui brings | No CDN: a UI served from a private network has to work on one |
| Lint | oxlint, plus `scripts/check_ui_classes.py` and `scripts/check_ui_system.py` | A JS linter cannot see inside a `className`, so the type scale and the design system get checks of their own |
| Format | oxfmt, pinned exactly, configured in `.oxfmtrc.json` | Prettier's output from the linter's own project, and it sorts Tailwind classes against `src/index.css` rather than guessing at the theme |
| Tests | vitest in `environment: node`, playwright for the browser | |
| Packages | **bun**, always. Never npm, yarn, or pnpm | |

**Base UI is the primitive layer, and app code never imports it.** Pages and components import
from `@winterop-com/sokkel-ui/primitives/*` and nothing else reaches for `@base-ui/react` directly. That boundary is
what lets the component layer be swapped without a change anywhere above it, and other apps in
this family are on a different primitive underneath the same imports.

**A screen whose dependencies no other screen has is a lazy route.** `src/App.tsx` reaches it
through `React.lazy` and a `Suspense` whose fallback is the same `PageState` loading card every
read shows. The entry chunk is what every reader pays for on every screen, so it holds the login
screen, the two listings this app is mostly read through -- pipelines and runs -- and the 404,
and everything else is fetched when it is opened: run detail, a pipeline's page and the pipeline
editor, because React Flow is the canvas nothing else draws on; the dashboard at `/`, which composes a screenful
of reads nothing else composes; connections, triggers, schemas, blocks and examples, each
carrying the forms, the dialogs and the panels nothing else uses; and the three admin screens,
which most readers of this app are never offered.

**A chunk inside a lazy route is the same rule again.** Every pane in this app that writes
source or windows it mounts `components/pipeline/CodePane`: the editor's source pane, a step
config field whose schema published a `contentMediaType`, a schema document, an alert rule's
body, an example's text, and the read-only window a produced value is opened in. `CodePane` is
the one `React.lazy` reaching `components/pipeline/CodeEditor`, so opening a pipeline does not
fetch an editor and opening its source tab or a jq step does. That wrapper is the whole of what
dirigent adds to the library's editor: the language a media type is read in, the library's JSON
Schema 2020-12 meta-schema (`JSON_SCHEMA_2020_12`) for a schema document, carried in the bundle
rather than fetched, the reader's caret-line preference, the word the schema check says beside a
deprecated key (`SCHEMA_CHECK_WORDS`), and the marks and reveal the schema tester draws in its own
offsets. The library reads
JSON, YAML, jq, SQL, shell and Jinja itself and loads SQL, shell and Jinja the first time a
buffer shows one; FHIRPath and CQL are dirigent's, written as CodeMirror stream parsers in
`lib/program-grammars` and handed to the library's `defineLanguage`. The schema checker, ajv,
compiles each schema into a function, which is why the UI policy's `script-src` carries
`'unsafe-eval'`; the policy for the API viewers does not.

**An engine is fetched when the screen that needs it mounts, and not with the screen's code.**
elk is the second of them: `components/graph/elk` is the one dynamic import of
`components/graph/elk-engine`, so the graph screens' chunk carries React Flow and the canvas, and
the 1.4 MB of layout algorithm arrives only once a canvas asks for geometry. It arrives in a web
worker -- `elkjs/lib/elk-api` wrapping `elkjs/lib/elk-worker.min.js` -- so placing a fifty-step
graph is not work the thread that draws is blocked on. sokkel-ui-graph is handed the same worker
through `setElkEngine` in `main.tsx`, so the run's graph and the miniatures are placed there too.
Nothing waits on it to draw either: `placedByRank` places the ranks by hand, wrapped onto rows at
the same `WRAP_WIDTH` elk is handed, and that is what a canvas shows until elk answers and what it
keeps showing if elk never does; the library's views do the same with its own `rankLayout`.

**A chunk two screens want is fetched before either is asked for.** `warmEditor` and `warmLayout`
are those same imports, fired by the shell once there is a session and the browser is idle --
`lib/idle` is `requestIdleCallback` where there is one and a timer where there is not -- so the
first source tab, jq step or output window of a session opens against a chunk that has already
landed, and the first canvas is placed by a worker that is already running. Nothing waits on
either, each happens once, and the login screen is outside the shell and asks for none of it.

**No chunk is over vite's default 500 kB, and the limit stays the default.** elk's worker is
larger and is not a chunk at all, so the warning still means something when a chunk grows.

**oxfmt owns whitespace, quotes, semicolons and the order of Tailwind classes**, at four spaces,
single quotes outside JSX, no semicolons and a print width of 110. Nothing about that is worth an
opinion in review: run `make ui-fmt`. `make ui-lint` runs the check first, so an
unformatted file fails the gate before anything else is read.

`make ui` builds the bundle, `make ui-dev` serves it with hot reload against a running `dg dev`,
`make ui-lint` and `make ui-test` are the gate, `make ui-e2e` drives a real server in a browser
and `make ui-shots` photographs every screen for the gallery. `make docs-shots` is the other camera:
nine screens, the `amber` palette in dark mode at 1440x900, shot against the showcase shelf
and committed under `docs/images/screens/` because [Screens](screens.md) renders them. `make ui-static` puts the built
bundle where the server wheel packages it, and it comes before every e2e run and every live
review, because that packaged copy is what a checkout's `dg dev` serves. The gate is wired into
`make check` behind a check for bun, so a machine without bun gets a loud skip rather than a
failure.

## Five type sizes, and the named sizes outside them

The scale is sokkel-ui's: 13px, 15px, 16px and 24px, with a section heading at the prose size and
a heavier weight. Nothing arrives beside it without a name. The faces are IBM Plex Sans and IBM
Plex Mono; a page has a heading somebody can find from across the room, and the working size of a
dense screen is a step under its prose. A size dirigent needs that the library does not have is
added in sokkel-ui.

| Class | Size | What wears it |
| --- | --- | --- |
| `text-xs` | 13px | Codes in mono, chips, counts, timestamps, a status word -- anything read at a glance rather than as prose |
| `text-sm` | 15px | The working size: a control's word, a rail entry, a row's description, a fact, a table cell |
| `text-base` | 16px | Prose: a description's body, a failure's message, a dialog's sentence, the command palette's search field |
| `text-title` | 16px | A section heading and a listing row's title, at weight 600 |
| `text-page` | 24px | A page heading, at weight 500, and nothing else on any screen |
| `text-stat` | 32px | A stat's number, and nothing else on any screen |
| `--text-graph-title` | 12px | A step's title on a graph -- at weight 500 on the editor's canvas and 600 on the pipeline page's and a run's, in mono where it is the key -- and nothing else on any screen |
| `--text-graph-small` | 11px | Every other word drawn on a graph: the block or what a source listens to, a badge, a count, a duration, a fan-out's strip, words standing over an empty canvas |

**Mono is for what is typed somewhere else**: a code, a step's key, a block, a kind, a duration, a
log line, a JSON value. A title, a heading and a sentence are in the sans face, and a code inside a
sentence is mono at the sentence's own size through `text-[0.88em]`.

The sign-in screen's sizes are sokkel-ui's `SignIn`'s own -- its brand name, its title and its
eyebrow -- and no screen of this app sets a size there.

A graph has two sizes of its own, because it is drawn at the scale of a diagram rather than of a
page. On the editor's canvas they are set on `.step-node` and `.graph-words` in `index.css`
rather than on each word, so a word added to a box inherits its size and no word on a canvas can
come out at the page's; the pipeline page's graph and a run's are sokkel-ui-graph's, which sets the
same two tokens itself.

`scripts/check_ui_classes.py` fails the gate on anything outside them, whether the sixth size
arrives as `text-[17px]` or as `text-lg`. The check has no allowlist -- it knows `text-title`,
`text-page`, `text-stat` and the two graph sizes by name, and
reads `index.css` itself so another size cannot be minted there either. A named
exception can be counted; an allowlist is a check people argue with. A library primitive that
carries a size off the scale is fixed in sokkel-ui.

A relative size composes with the scale rather than escaping it, so `text-[0.85em]` on code inside
a sentence is deliberate and passes.

## Tokens

Everything colour is a CSS custom property defined by sokkel-ui's tokens and themes, exposed to
Tailwind through the library's `@theme inline`. Nothing in this app may write a colour; a token
the app needs and the library lacks is added in sokkel-ui.

**Two theme axes, kept apart.** The **mode** is light, dark or system, worn as a `dark` class on
`<html>`, following the operating system until somebody says otherwise. The **palette** is which
set of colors the app spends inside that mode, worn as `data-theme` on the same element. Neither
axis knows about the other.

**sokkel-ui keeps both; dirigent only names what it offers.** `useAppearance(APPEARANCE_DEFAULTS)`
runs at the root in `src/main.tsx`, and on the Theme pane that writes through it; it stores the
choice under the library's keys (`sokkel-ui-scheme`, and `sokkel-ui-appearance` as JSON) and writes
it on `<html>`. A component that needs only the mode reads `useScheme()`. Before the first paint,
the library's `appearance.js` writes the stored look so there is no flash: index.html loads it at
the top of `<head>`, right after the charset, as
`<script src="/appearance.js" data-theme="amber" vite-ignore>`, and the `data-theme` there is the
palette a browser with nothing stored starts in, which a test holds equal to `DEFAULT_PALETTE`. **It
is a same-origin file and never inline**, because the server's policy allows scripts only from `'self'`;
`vite.config.ts` emits the library's built file beside index.html and the dev server answers the
same bytes, and `vite-ignore` keeps Vite from taking the tag for a module to bundle.
`src/lib/theme.ts` holds the names, the labels and the defaults, and stores nothing.

**A palette is one of sokkel-ui's themes: one import and one row, and nothing else in the app
learns it exists.** The import is the theme's file, `@winterop-com/sokkel-ui/themes/<name>.css`,
in `index.css`; the row is in `PALETTES` in `src/lib/theme.ts`, carrying the name and the label. A
theme file hangs off `html[data-theme='<name>']` and **answers to `[data-theme-scope='<name>']` as
well**, so an element inside the app can be painted in a palette the document is not wearing --
which is what a palette's card on the Theme pane is, and why a card cannot drift from the tokens it
stands for. A test asserts every palette is imported. `PALETTES` is also the list the app offers
the library, in `APPEARANCE_OFFER` and in the pre-paint script's `data-themes`, so a stored theme outside it gives
way to amber before the first paint. A theme dirigent needs that the library lacks is added in
sokkel-ui, never here.

**Both axes are chosen on the settings dialog's Theme pane, as two rows, each searched on its
own.** Appearance is sokkel-ui's `SchemeChoice`: System, Light and Dark, in that order, one
segmented control rather than a menu, because a choice from a fixed set of three is one control and
not a list to open. **Palette is sokkel-ui's `ThemeCards`, one card per palette**, because what a
palette is is what it looks like: each card is a small page in that palette's own tokens -- its
ground, a bordered card on it, a line of ink and one of muted text, the brand -- in the mode the
app is wearing, so a palette that changes the surfaces and lines shows them as plainly as one that
changes the accent, and no palette carries a line about itself. The cards are the Palette row's
control, under its title. Neither row holds a copy of what it sets -- both go through
`useAppearance`, the one store the root wears and the account menu writes. **The mode is also three
radio rows in the account menu**, the same three writing the same store, because it is the one
look somebody changes in passing; the palette's Appearance rows are the third door to it. **The top
strip carries no mode flip**: the account menu stands on every screen, and a control said twice on
one screen has to earn the second time, which a two-way flip that cannot reach System does not.

**Three palettes ship, ordered quiet to loud: `amber`, `paper`, `contrast`.** The default is
`amber`: the library's neutral blue-grey surfaces under an amber accent, in a dark and a light mode;
`paper` is the same app on warm paper with warm ink; `contrast` is white on black and black on
white with every line and every ink pushed to meet 4.5:1. **The amber is the brand in every one of
them**, and a palette moves its lightness only where its own ground needs it. **The surface ladder
keeps its order and roughly its steps** in every palette, so a component designed against the
rungs still reads -- except where a palette's whole point is the ground it commits to, and
`contrast` collapses page and card onto one white and one black, drawing every card by its edge
instead of its shadow.

**Every section of a page is a headed panel.** sokkel-ui's `Section` is the one surface a page
draws: a title bar on `--section-head-ground` with the section's label at the left and its count or
a fact about it beside the label in mono, the `--section-head-line` rule under the bar, and the
body on `--card`, edged all round in `--border-strong` and lifted by no shadow -- the line and
ground of a framed `DataTable` and a card. A panel holding a graph is `tone="graph"`, its body the
graph canvas's dot grid, because a graph is drawn on a ground and not on a card. **A failure is the
one panel that says so**: `tone="critical"` draws a rule in the critical tone along its top and the
warning mark beside its title, which is the only colour a panel ever carries. Nothing draws a left
border in a status colour, and nothing on a screen styles a surface of its own: a treatment is
changed in sokkel-ui, and the run terminal's frame and the generated card follow it in the
`.dg-panel` rules in `index.css`.

**Every panel's title bar is one fixed height, so bars side by side line up.** The bar is the
library's `--density-panel-head` -- 36px, 32px in the compact density -- the height a listing's
head row is drawn to, so two panels standing beside each other put their labels on one baseline.
A control in a bar is compact, `xs` or `sm`, and fits the bar rather than growing it. A failure's
rule along the top adds no height to the bar. The run terminal's toolbar is the one bar of its own,
`.dg-panel-head` at `--spacing-panel-head` -- 40px, and 46px below the breakpoint, where a control
in it is a finger tall -- and the one bar that may wrap onto a second line, and only below the
breakpoint, because it stands alone and carries filters rather than a label.

**A listing is a headed panel too.** sokkel-ui's `DataTable` with `variant="list"` draws
`Section`'s edge and ground: its row of column headings is the panel's bar, and its rows stand on
the card with a hairline between them. A titled listing is a `Section` with `flush`, the count in
its `meta`, around a `DataTable` with `framed={false}`, its headings under the section's bar, so a
screen with two listings -- Triggers' sources and schedules, the catalog's families -- is two
panels rather than two headings over two cards.

**Inside a panel or a dialog there are three boxes, and each is drawn once.** sokkel-ui's
`Surface` with `tone="well"` is a group that belongs together -- a form opened under its row, a
sample -- on the panel ground, edged in `--border`, and `pad` insets it by the density's panel
padding. `tone="inset"` is reference material -- a block of JSON, a code block in a description
-- on the page's own ground, edged the same way, so a preview reads as cut into the surface it is
on. A log that scrolls and follows its tail is the same inset, holding the scroll through its `ref`.
A code editor is a field, and the library's editor edges itself the way every field is edged --
the `--input` hairline at the control's corner -- unless it fills a panel of its own. A box that says how something is going is sokkel-ui's
`Callout`, and a refusal off the wire is `Refusal`. No screen types a border, a corner and a
ground onto a `div` of its own.

**The rest of the ladder.** `--sidebar` is the rail, a rung under `--background`, the page.
`--secondary` is raised: a button's fill, a chip, the active rail entry; `--popover` is a dialog
and a menu, raised by `--shadow-pop` over a `--scrim`, which is the one shadow left. `--node` is a
box on a graph. A control has a ground of its own, `--field`, which is the page's, edged in
`--input`, so an empty box reads as a box in both modes. `--muted` is the wash a row takes under
the pointer. `--border` is the hairline between rows inside a panel body; `--border-strong` is the
shell's rule. Ink runs `--foreground`, `--muted-foreground` for a hint and a code, `--faint` for a
timestamp beside a name. Every surface stays near-achromatic, so status colour is the only colour
a screen carries.

**The amber is the brand, the reader's avatar and the focus ring, and nothing else.** `--brand`
fills the mark and the avatar at the foot of the rail, and `--ring` is every focus ring. **An action is drawn in ink**: the primary button is `--primary`,
which is the foreground as a fill with the page's colour on it, so the one loud thing on a strip is
the verb somebody came to press rather than a colour. A secondary button is `--secondary`, a
quiet one is ink on nothing, and a verb that takes something away is the critical ink on
`--critical-wash`. **Selection is neutral**: the active rail entry is a `--secondary` fill and
weight 600, a chosen box on a graph is a ring in the foreground, and a chosen row is the
`--muted` wash held.

**`--primary-ink` is the amber as text, and it is worn by the door's eyebrow alone.** A link is
ink, underlined on hover, and an aside link beside a section heading is the muted ink: a link
names a place, and a place is not news. `scripts/check_ui_classes.py` refuses a bare
`text-primary` anywhere in the app's own source, because the primary is a fill.

**Status is named for the state machine.** `--status-succeeded`, `--status-failed`,
`--status-running`, `--status-waiting`, `--status-queued`, `--status-pending`,
`--status-completed-with-errors`, `--status-cancelled`, `--status-skipped`. The names are
`RunStatus` and `AttemptStatus` from `dirigent_client.enums`, so a status string off the wire
indexes a token with no translation table. Each has an `-ink` twin: the token fills a chip at 14%
alpha and the ink is what is legible on it -- sokkel-ui's `StatusChip` is that rule, written once,
and `STATUSES` in `lib/status` is the one map of each state's word, color and whether it is live,
handed to every status part through the `StatusProvider` around the app. The provider gives
every chip its dot, and draws a state this bundle was built before in the pending pair rather
than uncolored. A delivery is a machine of its own, so `--status-sending` and `--status-sent`
are `NotificationStatus`'s live states written as the run states they mean -- in flight is
running, arrived is succeeded -- and a palette that moves those moves these. `skipped` is drawn
in neutral with a dashed edge, because a skipped step did not happen and has not earned a
colour.

Four semantic aliases sit over the top for anything that is not a run: `--good` is succeeded,
`--critical` is failed, `--warning` is completed-with-errors, `--info` is running. Each has an
`-ink` twin as well, for text on its own 14% fill.

**A kind is not a status, and has its own family of hues.** What a thing *is* -- a block kind, a
connection kind, the clock a schedule fires on -- takes `--kind-<family>` and the `.kind-chip`
fill rule, which is the status chip's written once more against tokens that cannot be confused
with a state. `lib/kinds` maps a kind to a family and hashes the ones this bundle was built
before, so the mapping is total and stable; no component writes a tint inline. Every family is
far from hue 80, because that hue is the identity colour and means action.

**Both modes, every time.** This app was designed dark first and the light one is its
inversion, not a second design: the same hues, the lightness ladder turned over. A token changed
on one side is checked on every surface that consumes it on the other -- an amber that reads as
the brand on near-black can read as mustard on near-white, and a raised fill that is a clear step
on the dark page is white on near-white in the light one, which is why a secondary button there
also carries a hairline ring. The light mode's shadows are a fraction of the dark mode's, because
a shadow on a pale ground reads as dirt long before it reads as depth. A palette is checked the
same way, on both of the modes it has.

**The app has one decorative element, and it is on the login screen.** The screen is sokkel-ui's
`SignIn`, and the art over its brand pane is the library's `FlowLines`: a few steps in columns
joined by curved lines, one run through them lit in the primary and flowing toward the last
step, which glows. It is the shape every screen behind the door draws, which is what earns it
the place. Nowhere else in the app is a shape drawn that does not stand for something the reader
can act on or read a value from.

**The door is the library's, and its layout is too.** The brand pane is half the window, dark in
both modes in the theme's own dark tokens, with the rail's mark on a tile in the primary, the word
`dirigent` and two facts under it: the host the reader typed and the version `/config.json`
answered with, which an unauthenticated door can know. In a narrow room it becomes a bar over the
form with the mark, the name and the host, and the art is left out. The seam between the panes is
dragged (`resizable`), and a double click puts it back. The dragged width is kept in this browser
under `dirigent.login.pane` for the next visit, and putting the seam back forgets it.

**The door's refusal is the server's own sentence**, a wrong password and a rate limit alike,
said in the library's critical alert over the button. It is the one refusal in the app not drawn
by `Refusal`, because `SignIn` draws it. After a refusal focus is on the password with its text
selected, so the next try is typed straight over it.

**The door asks for a username and a password, each led by its icon, with a toggle that shows
the password.** The fields carry no placeholders: their labels name them. The door opens with
focus on the first empty field: the username, or the password when the username is remembered.
The button is held until both are filled and while a try is under way, and held is
`aria-disabled`, never `disabled`: the button and the fields keep their focus through a try, and
the fields are read-only while it runs. The username this browser last signed in as is filled in
on the next visit, kept under `dirigent.username` only after a good sign-in, so a refused one is
not remembered; the password is never kept by the page. The fields are named and required, with
`username` and `current-password` for the browser's password manager.

**The radius ladder is crisp, and it is the floor as well as the ceiling**: 4px for a surface --
a card, a listing, a panel, a dialog, a menu, a graph's ground -- and for a box on a graph and the
brand tile; 3px for a control; 2px for a chip and for a box on a miniature graph. They are stated
in `@theme` rather than derived, as `--radius-surface`, `--radius-node`, `--radius-control`,
`--radius-chip` and `--radius-mini`, and every component takes its corner from them: no class
names a radius of its own. A ladder of 1 and 2 read as square and one of 8 and 6 as soft, so this
one goes neither below nor above. Nothing but a status dot and an avatar is fully round: not a
chip, a switch, a port on the canvas or a scrollbar. Tailwind's rungs are mapped onto the ladder
-- `rounded-sm` is the chip's 2px, `rounded-md` and `rounded-lg` the control's 3px, which is
what the generated buttons and fields ship, `rounded-xl` through `rounded-4xl` the surface's 4px
-- so a shadcn primitive lands on it without being edited, and a generated `rounded-full` is said
back onto a rung in `index.css` against its slot.

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
  `code`, `params`, `problems`, `instance`. `code` is the dotted code of the catalogued message
  the detail was rendered from and `problems` is a list of issues, each with its own `code`,
  `message`, `params` and `location`. There is no `type` member; this server emits none, so
  nothing may key off one. `apiJson` throws it; `apiFetch` hands back the `Response` for a caller that cares about
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

A page holds its own reads in `useState`, and a fact that genuinely spans screens -- who is
signed in, whether the rail is collapsed, which palette is painted, how often a watched screen
reads itself again -- is a module store from `src/lib/store.ts`, read in a component through
`useStore`. `store.ts` imports no React, so a store is exercised in plain Node. That is the whole
of the state layer: no react-query, no swr, no zustand.

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
source, an alert rule -- carries the same four fields, and the UI renders them the same way
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

**A code in mono never wraps mid-word.** `report-daily-digest` broken onto two lines at `daily-` is
a different string to somebody copying it, so a code is one line and nothing else: where it does
not fit it truncates with an ellipsis and carries the whole of itself on `title`. sokkel-ui's
`InlineCode`, `bare` at `size="xs"`, is that rule written once, and every code on a screen -- beside a title, in a fact, on a node, in a
row -- is drawn through it rather than through a bare `font-mono` span.

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

**The chosen row's code is in the address.** Schemas and Connections put the code of the row
somebody opened, in a panel or in a dialog, into the URL and read it back from there, the way Pipelines does, so a schema or a
credential is a link that can be sent rather than a selection somebody else has to find.

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
scheduler will not make. The panel lists no firings for it, and the chip beside its name is
what says paused. A saved cron clock is drawn in the panel by the library's read-only
`CronField`: the expression, its zone, its reading in words and the next firings the instance
reads back, so the panel carries no separate clock, zone or next fact for it. A paused cron
clock is the same field marked `paused`: it asks the instance nothing, keeps the expression, its
zone and its reading in words, and draws no firings, no heading over them and no words in their
place, since the chip already says it. A schedule with no next instant at all says nothing is
scheduled rather than drawing a dash, and that reading comes first: a one-time schedule pauses
itself once its moment has gone by, so the flag alone would have a spent clock read as a stopped
one.

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

**A clock being declared is read back by the instance, once, under its box.** The new schedule
dialog sends what is written to `POST /schedules/$preview` a moment after the last keystroke,
and what comes back is the one reading of it: the core's own arithmetic, so the dialog cannot
promise a firing the scheduler would not make. The zone is chosen first, in the timezone picker
above the clock, and that picker is the only place the dialog names it. A cron clock is
sokkel-ui's `CronField`, with `0 5 * * *` as its placeholder and no zone beside its label: the
expression read back in words from `triggers.schedule.reading`, and the three firings the instance
answers with, each on the zone's wall clock and spelled as `formatMoment` spells the other clocks'
firings. The field always holds the instance's verdict, so the field's own parse never marks an
expression the core reads. The last day (`L`), the last weekday (`LW`), the weekday nearest a day
(`15W`), the nth (`5#2`) and the last (`5L`) day of the week are read back in words like any
other expression. Until the answer for what is written now arrives, the field's own count shows muted
beside "Checking"; a refusal is the field's issue, in this interface's sentence for its code, it
shuts Create, and a refused expression is not read back in words. An empty field says nothing yet and draws dashed rows. An interval and
a one-time clock keep a plain box with the firings in one muted line under it.

## A listing is a cursor walk

Every screen that draws a listing draws it with sokkel-ui's `DataTable`, spread with `LISTING`
from `lib/design-system`: the list look, columns that do not drag, and the narrow form below. The
table is the panel, the heading row, the hairline between rows, the next page and the count; a
screen decides its columns, what each cell says and what a row does, and nothing else. **The
column header is sticky**: rows scroll beneath it inside the listing's own scroll container, and
the header keeps its ground so no row ever shows through it. **A listing that fills the page asks for
its next page as the rows near the end of its box**, and End on the keyboard reaches it the same
way. **A listing set in a `Section` among others** -- Triggers, Alerting -- grows with its rows
rather than scrolling in a box of its own, so it would reach its end at once and read every page;
it draws a button after its last row instead, saying how many the next page brings
(`SECTION_LISTING`). The count is the `foot` from `rowsRead`, or the `meta` of the section a titled
listing stands in. **A listing narrowed by a search or filters draws them in the table's own bar**:
the box is `DataTable`'s `search` and every other control its `toolbar`, so the search and the
count share the first line and the filters take a line of their own under it, wrapping from the
left edge -- and on a phone the filters take their own line with or without a search. The bar's
count is then the listing's count, in `rowsRead`'s words through `countWords`, and the listing
draws no `foot`. The table stays standing while a filter's answer is read, its rows the loading
placeholders, so the box keeps its caret; no rows say `empty`, and a refusal is drawn there too,
under the bar, so a filter that was refused can be taken off. **A filter is sokkel-ui's
`FilterChip`**: unset it says its facet and a chevron, set it says the facet and the value on the
accent's wash and carries the X that clears it, and its menu is the facet's values. A `Segmented`
among the filters is `size="md"`, so the search, the chips and the segments are one height. The
count is left out while the table says it is empty. A screen whose search narrows several tables
or a list that is not a `DataTable` -- Blocks, Pipelines -- draws sokkel-ui's `ListingBar` over
them, the same bar `DataTable` draws, and gives each table `bar={false}`. Where a row opens something -- a trigger's history beside the table, a
connection's dialog over it -- the screen passes `onOpen` and `opened`, and the row answers Enter
on the row the arrows reached as well as a click, because a row only a pointer can open is a row
some people cannot. A row that is no longer live -- a paused or switched-off alert rule, a stopped
worker, a deactivated account, a revoked or expired token -- is drawn `rowTone` `muted`.

**A row on most listings fills the panel, and that is a disclosure, so pressing it again takes it
back.** What a press
opened a press closes: the row loses its tint, the screen stops filling the panel, and an
unfilled panel is not drawn -- so the thing opened from the listing can be shut from the listing,
rather than only from the panel's own control. A row whose selection is the URL navigates back to
the bare listing instead, which is the same gesture said in the address bar. `useRowPress` decides
this for every listing that fills the panel, from what is open and `panelStanding`, and a screen
says only what opening a row and taking it back mean. **Pressing the open row while the panel is
down opens it again** rather than clearing a tint nothing is showing, because a control that does
nothing is the fault this rule exists to fix. **A row that navigates is not a selection** and does
not toggle: the runs listing goes to a screen, and a press there has already left. **Connections and
Users are the two listings whose row opens a dialog instead, and the pattern is still being tried**:
see below. No other listing has moved, and none should until that trial has been read.

**Every listing is a keyset walk**, answering rows and an opaque cursor and no total, so there
are no page numbers and what the foot can honestly say is how many rows have been read and
whether there are more. `lib/paging` is what an answer does to the rows already held, as pure
functions over the state; `hooks/use-paged` is the part that needs a browser, and it holds the
question beside the rows so an answer to filters somebody has since changed cannot land on the
screen.

**A trigger row is two fixed lines.** The lead cell is `headingOf`'s pair -- the title, and the
code beneath it in mono only where the title is not already the code -- and everything else the
row has to say about itself goes on that second line as a chip: the document that owns it, or
`managed`, and `paused` or `disabled` where that is true. There is no kind chip, because the
heading over the table is the kind, and no id, because a row's key is not something a person
reads. A row whose height depended on how many chips it wore would make a listing of twenty rows
a listing of twenty heights.

**A connection row is two lines and three cells.** The lead cell is `headingOf`'s pair drawn
across -- the title, and the code in mono where the title is not already the code -- with the
description's first line under it in the muted ink, truncated, which is what a credential is for
said in the words of whoever set it up. Then the kind, its mark and its code in mono, and the
health. What a credential is pointed at is read on the connection's own dialog: a settings line
per row is a column of `url=` and `timeout=` to scan past before the health cell is reached.
**A healthy connection is a bare dot, and failed or
unknown gets the word**, which is the top bar's rule: words only when something is wrong. The dot
is 8px; the words are `healthOf`'s -- `failed`, `never checked`{ .label }, `not verified`{ .label }, and `healthy` as
the bare dot's tooltip -- in the channel strip's three colours: green where the last check
passed, red where it failed, a hollow ring where nothing was proved. One vocabulary, decided in
`lib/connections` and drawn by `HealthSaid` on every screen that draws a credential's health: this
listing, a pipeline's requirements, the reference row under a field. **The check's own sentence is
not on the row**: it is the tooltip on the health cell, on hover and on keyboard focus alike, and
it is in the connection's dialog in full, where there is room for the whole of it. Checked
is how long ago, and nothing at all where nothing has ever asked -- so a row nothing has checked
has no Checked line on its card either. Asking again is the dialog's `Check now`{ .label }, not a button on
every row.

**Connections opens in a dialog, shown first and edited second, and this is a trial, of which Users
is the second use.** Pressing a
row opens one dialog over the listing, at `/connections/<code>`, and there is no panel on this
screen. It reads first: the title, the kind and the code; the description; then the health with
the check's own sentence, every setting that holds a value under its own key, every secret as dots
or `not set`{ .label }, and when it was made and changed. Its footer is `Delete`, and `Check now`{ .label } and `Edit`
at the other end, with the corner's close as the way out. `Edit` is the same dialog in its edit
state, at the same width, so nothing moves under the hand: the kind's schema form, its secrets
sealed in it, a footer of `Cancel` and `Save`, and no corner close. Cancel, Escape and a press outside all go back to the reading rather
than closing, and a press outside does nothing at all while a form is open, because a typed
credential is not something to lose to a stray click. A save checks the connection, because the
health on screen was about the settings that were just replaced. `Delete` raises `ConfirmDialog`
over the dialog. **What uses the credential shuts it**: `GET /connections/{code}` answers `used_by`
-- the pipelines whose current version names the code with the steps and sources that do, the alert
rules delivering through it, the storage schemes configured from it -- and where any of that is true
the reading draws it as a `Used by` fact, each one linked where it has a screen. The same read is
made again as the question opens, and the question says `Used by <what>.` with Delete shut and saying
why. The server checks again at the delete and holds what it finds, so a refusal for what that read
did not see stays in the question as one line. `GET /connections` carries nothing about what uses a
credential, because a listing would have to walk every document for every row.

**An account opens the same way, and is the trial's second use.** A press on the row, anywhere but its
chevron, or Enter on the row the arrows reached, opens one dialog over the listing that reads first: the title, the role, the email where
there is one, when it last signed in and when it was made. Its footer is `Deactivate` (or `Activate`),
and `Reset password` and `Edit` at the other end. `Edit` is the same dialog at the same width: name and
email side by side, the role as one compact select with what each role may do on its option, a footer
of `Cancel` and `Save`, and no help line that does not add a fact. There is no panel on this screen.
There is no single read of an account, so the open one is not in the address. **A role is a word and
not a code**: plain in the Role column and in the reading, and never a chip beside the mono username
it could be mistaken for.

`hooks/use-read` is the one-page sibling of `use-paged`, for a read that is a document rather than
a listing -- what this instance has installed, how the last day of runs came out. Same rule: the
read function's identity is the question, and an answer to a question nobody is asking any more is
discarded rather than left on screen.

**A screen that watches beats, and the rest are read when they are opened.** A run's own screen
holds one event stream and needs nothing beside it. Two screens go stale standing still -- the
runs listing and the dashboard -- so each reads itself again on the one
cadence `lib/refresh` holds for the whole app: off, or five seconds to five minutes, thirty by
default, chosen from the split refresh control and answering the same everywhere it is offered.
`hooks/use-heartbeat` is the beat. It fires only while the tab is visible, because a screen
nobody can see asking anyway is heat, and it fires at once when the tab comes back, so what a
reader returns to is the present. A beat is quiet: what is on screen stays until the answer
lands, a beat that fails changes nothing and the next one asks again, and a listing's beat folds
page one in at the head matched by id -- so a row already on screen is refreshed in place rather
than moved, and the count of what arrived is the pill the runs screen offers.

**A filter is the server's or it is not offered.** `GET /runs` narrows by pipeline, by status,
by how far back to look and by the tags the run's pipeline wears, and those four are what the
runs screen has. A control for something the server cannot filter would narrow whichever rows
happen to have been loaded while appearing to answer the question it asks. Where a screen does
narrow what it has loaded -- finding a pipeline among the pages read so far -- the foot already
states how many rows those are. A corpus is the exception, and it is one because nothing in it is
unread: the block catalog and the examples screen are answered whole by what this build
installed, so every control on them narrows all of it and their empty state can say a search
found nothing rather than that there is nothing yet.

**An examples row says what a copy of it would have to change.** A document carrying a top-level
`connections:` or `schemas:` section is what runs alone under `dg run --local`, and an apply
refuses it, so the row states `carries connections; a copy names them` -- `carriesNote` in
`lib/examples` -- and a template's copy names them under `requires` instead. A document carrying
neither says nothing, because a column saying "nothing" of a hundred rows is a column of noise.

**A tag filter is a set, and the chip spells its members.** `tag` repeats on the wire and
repeating it narrows, so `components/list/TagFilter` is a `FilterChip` with `multiple`, its
menu rows the tag chips and its face the chosen tags in mono -- the first and `+N` past two --
and its X clears the set. A tag the address names stays on the chip even before the menu of
offered tags has been read. Where a row already draws its tags,
the chip on the row adds it to that set: the filter is reached from the thing that shows what to
reach for. Where a row's tags would be the same words repeated down a column -- every run of one
pipeline -- the rows carry none and only the filter does, and a pipeline's row carries none
because its shape and its sentence are what it says about itself. On the pipelines screen the set
lives in the address (`?tag=`) so a narrowed listing is a link somebody sends, and it is replaced
rather than pushed, because a filter being assembled is one destination and not five. The runs
screen carries the same control beside its own three, seeded from the address once and held in
state after: a control that wrote every keystroke back would put a history entry behind each one.

**A tag on a row is the filter's own door.** `components/TagChip` is a chip until it is given
`onSelect`, and then it is a button saying "Filter by <tag>" that adds that tag to the set the
listing is already narrowed by rather than replacing it, because a tag drawn on a row somebody
cannot press is a fact with a gesture missing from it.

**A column's heading is a label, whatever the cells under it are.** A column of codes draws its
values in mono and its heading in the sans face, because the heading is the same word in the same
voice on every listing.

**A column holds a value, a title or prose, and that is what decides its width.** Every row of a
`DataTable` is a grid of the same tracks, so a width is declared, never left to a cell's content.
**A title carrying a free-form name is a `minmax(<floor>,2fr)` share**, cut in it with the whole
of the name in `title`, because a name has no longest case. The code drawn with that name is never
what gives way: beside the name it keeps its width (`shrink-0`) and the name is cut, under it it has
a line of its own, and either way the share's floor is wide enough for a long code to read whole
at `lg`. **A title that is a code or a word
from a fixed vocabulary is `width: 'content'`** -- a block id, a worker, a token, a status -- as
wide as its widest drawn cell up to its `maxWidth`, so a reader tells one row from another before
anything else is given room. Users' Account column is `content` with a `minWidth` of 14rem. A
measured `content` column counts toward the listing's least width, so a wide one stacks the rows
sooner. Prose under such a title is not measured: a Blocks row's summary is a `TableCellFill`,
cut in the width the id and its chips gave the column -- never under its 16rem `minWidth` --
with the whole of it in `title`, so the families' id columns line up on the ids. A value
-- a chip, an instant, a duration, a count, a mark -- is drawn from a fixed vocabulary and
declares the floor it needs to say itself on one line as `minmax(<floor>,1fr)`, sharing what the
title left. Prose -- a description, a path, the sentence a run failed with -- is
`minmax(<floor>,2fr)` or more, so it takes the larger share and is the column that is cut. A
control is a fixed width. Inside a cell, text that can run long carries `min-w-0` and `truncate`
and says the whole of it in `title`, or the cell shrinks and the words are simply cut off.

**A listing's least width is what turns it into cards.** `LISTING` sets `minWidth` to 36rem: the
table never draws narrower than that or than the floors of its columns, and a box narrower than
either stacks its rows (see Small screens), so no listing scrolls sideways.

**A card's rows follow the same rule as a listing's columns.** The dashboard's health card
lines a mark, a code, what the thing last said and when up on one line in a card a third of the
screen wide, which is a table's problem in something that is not a table. A healthy connection says
nothing there, its dot's tooltip carrying the word and the check's sentence: the mark is a value
and holds its width, the code is the identity and keeps a floor of six characters, what it said
is prose and truncates in what is left with the whole of it on its title, and the instant is a
value out of a fixed vocabulary and holds its own. Nothing on such a row is `shrink-0` unless
it is short by construction, or the row's minimum is wider than the card and the card scrolls
inside itself -- the same defect as a listing that scrolls sideways. A card whose row cannot be
read at a third of the width takes the whole width instead: the chart's column and the health
column share a row at `xl` and stack under it.

**The dashboard says what needs somebody first, then how things are going.** Its first section is
the runs that need a look -- every pipeline whose newest run failed or completed with errors,
one row each, led by the pipeline's miniature with the failed step filled, then the title and
code, the step and the sentence it failed with, the status word, how long ago, how many runs
that is where it is more than one, and the catalogued code. Where nothing needs a look the section
is not drawn, because a heading over nothing is a wall of one zero. Then two columns: the runs of
the last day by the hour, with the failed and the troubled parts of each bar in their hues and the
rest in a neutral ink, because a green bar is the loudest thing on a page where nothing is wrong;
and under it how long each pipeline took, the median of its runs in that day. Beside them the
health of what the runs depend on -- each connection that is not healthy by name with its word,
a count of how many are, and every worker. Then the runs in flight, the most recent runs, one
line each, with `All runs`{ .label } beside the heading, and the next firings -- each of the three
only where there is any. There are no stat tiles: a number that is zero on a good day is a
number nobody reads on a bad one.

**The tags fold to the room they have rather than wrapping into it.** Chips are one line: a row
whose height depends on how many words it wears makes a listing of twenty rows a listing of
twenty heights, so what does not fit the Tags column folds into one trailing `+N` chip -- which
says how many it is holding, spells them on hover, and opens them as the same filter every
other chip on the row is a door to -- and never more than eight chips are drawn whatever the
room. **The fold is computed, not guessed**: a chip is mono at 12px, so how wide one is is
arithmetic over its characters, and `lib/tag-fold` fits the words -- the `+N` counted as the chip
it is -- into the width the Tags column is drawn at, which `TagChips` reads from `useTableCell`, so
the column is a share with a floor rather than a fixed width. On a stacked card the chips wrap
across the card, still no more than eight; outside a table they wrap.

**A choice closes on its choice; a set stays open.** A single `FilterChip` is one value out of a
menu headed by the row that unsets it (`filterWords(any)` in `lib/design-system`), and picking
one shuts the menu, because the question has been answered; `oneChosen` holds that one value as
the string the filters keep, `''` for none. A set is the other case: several tags mean AND, so
the tag filter's rows are checkboxes and the menu stays where it is until somebody is done with
it. Past eight values the menu is a list with a search over it, and the same rule holds.

**A count says what it counts.** `rowsRead` writes "1 pipeline", "50 runs, more to load": the noun
is the row's, singular where there is one of it, and a listing with a cursor left says so. A bare
number along a foot or in a bar reads as a total, and a keyset walk has no total to state. **The noun reaches
the foot in both numbers**, as the `{one, many}` pair its `count` entry holds, and `rowsRead`
takes that pair rather than a word: a foot handed one plural would have to reach the
singular by rule, and the rule that makes a batch out of batches makes an entrie out of entries.

## A pipeline is listed by its shape

**A pipeline's row leads with its miniature graph**, because what a pipeline does is the shape of
its steps before it is any sentence about them. sokkel-ui-graph's `MiniGraph` draws it from
`PipelineOut.shape` -- the current version's steps reduced to a key, a block or the kind a source
listens to, what each depends on and whether it fans out -- and from nothing else, so a listing of
fifty pipelines is one request. Then the title, the code in mono beside it, and the description's
first sentence under them, which is what a description's first sentence is written for. What
fires it and how it last ran stand after that **only where they exist**: a schedule count and the
kind of each source as chips, and the last run as its status word and how long ago. A pipeline
that has never run says nothing there, never "never run", because a column of the same words is
a column that says nothing. The row is the link to the pipeline's page, so it draws no arrow, and
the listing draws no panel.

**A miniature is drawn the same way everywhere**, by sokkel-ui-graph's `MiniGraph`. A box is about
14 by 7 pixels; a step that fans out is a box with a second one stacked behind it; a source is a
dashed box on no fill; a step the last run failed in is filled in the failed hue, which is the only
colour a miniature ever carries. The boxes are laid out by elk as the full graph is, read left to
right. An edge is drawn only where it changes the shape -- an edge another path already implies is
left out, so a step that waits for everything before it does not draw a fan of lines -- while the
full graph on the pipeline's page keeps every one. **The scale is shared and capped**: every
miniature is drawn at the same pitch, about 29 pixels per rank, standing at the start of the lead
cell, so a longer strip is a longer pipeline, until the cell's width is reached, and a pipeline
deeper than that is drawn smaller rather than cut. Pointing at a step names its key and the block
it runs or the kind a source listens to; the miniature's accessible name is the pipeline's title.

**A person's own pipelines and the shipped examples are two lists.** `PipelineOut.example` says
whether a pipeline's code is one the installed example corpus ships. The person's own come first,
in their own panel, at a row's full height, ordered by title. The examples come after, in a panel
of their own with denser rows: a short set, the ones
that have run first and most recently, and a link counting all of them to open the rest in place. A screen
whose examples outnumbered the person's own by twenty to one would otherwise be a screen about
the examples. Where every pipeline on an instance is an example, the person's list is not drawn,
and where none is, the band is not.

**The search box and the tag filter narrow both lists**, the tags on the server and the search
over what was read, and the counts beside each heading are what is left.

## The pipeline's page leads with its graph

**A pipeline's page is its graph first.** The title, the code in mono under it, and Edit,
Validate and `Run…` at the right of the heading; the description; then the graph on the canvas
ground; then what the pipeline did, side by side -- Recent runs, its newest runs one line each
(the state, what started it, how long it took and when, each line the link to its run) with `All
runs`{ .label } beside the heading opening the runs screen narrowed to this pipeline, and `No runs.` as
the whole body where there are none; and, only where the document declares a `report:` and a run
has settled, Report, the latest settled run's document rendered as the run's Report tab renders it,
at a pane's height with the window for the whole of it, the run it came from beside the heading,
and the settled runs before it as links to their own Report tab at its foot. A document declaring
no report, or a report and no settled run, draws no Report panel. `GET /runs?settled=true` is how the page finds
that run, because no single status asks for it. The two rows take the same flex bases, so the seam
between Recent runs and Report lines up with the one under it. Then three panels side by side -- Blocks, which block each step runs with the steps as
chips that choose them on the graph, drawn only where a step runs one; Triggers, the schedules and sources that fire it; and
Connections, what it reaches and how each one is. `Edit` opens the editor at
`/pipelines/<code>/edit`, which is the screen the rest of this page's editing rules are about;
`Validate` dry-runs the stored version against the instance as it is now and says the answer in
one line.

**The graph is fitted, never scrolled.** At 1440 wide a pipeline's graph is drawn whole on the
page with no scrollbar of its own: the canvas is as tall as the drawing it holds rather than a
fixed stage, the drawing is scaled down where it is wider than the page and never up past its own
size, and a graph too deep for the width is wrapped onto rows the way every canvas wraps one. It
pans, zooms, lays out and opens in a window as every view of a graph does.
Choosing a box says under the graph which block it runs, what it waits for and what it feeds, and
puts it in the address as `/pipelines/<code>/<step>`, replaced rather than added to.

## An endpoint says where it is called, and a run says who it answered

**An endpoint source is drawn as the address a caller is given.** Wherever a source a request
reaches is described -- its row in the pipeline page's Triggers panel, the editor's step panel
for it, the triggers screen's panel -- it says its methods and the full URL in mono, wrapped rather than truncated: this
instance's origin, the endpoint prefix and the path, which is the string a caller pastes, with a
copy button beside it. Under that, how a caller authenticates, as configured: a bearer token by
its prefix, an HMAC signature by the header it arrives in, or `public`. `components/triggers/Endpoint`
is that block, written once, and `lib/sources` is where the URL and the line are decided.

**`New token` is how a source's credential is replaced, and it asks first.** The verb is `New
token`, or `New secret` on a signed source, on whatever surface describes the source; it raises
`ConfirmDialog`, `Replace the token of <code>?`, whose one line is that the old one stops working,
because that is what the verb takes beyond the thing named. The answer is the minted-token dialog
every source credential is shown in: `SecretReveal`, the URL, how a caller presents it, and for a
bearer token a `curl` line that makes one call with it -- the first method, and the source's sample
body where it has one -- because the first thing anybody does with a new token is try it.

**A run says how its source was entered and whether its reply went anywhere.** A run of a pipeline
with a source was entered one of three ways a reader cares about: by a call, by hand with an input,
or by hand from the source's sample. The received attempt carries it as `via`, and the run's status
line says it after who started it: `by admin, from the sample`, `by admin, with an input given`,
`by a call to ask`. A reply renders whether or not anybody is waiting, and its output carries
`delivered`: the reply's box says `sent` or `not sent` after the word `reply`, in place of its duration, and its step panel
says `sent to the caller` or `recorded, not sent`. A hand run is answered nowhere, and the screen
never lets it look as though it was.

**`Run…` says what a hand run of a pipeline with a source does**, in one line over the footnote:
that it starts from the source's sample, or with an empty input where there is none, and that
nobody receives the reply where the pipeline has one.

## A graph is a shape, and each screen reduces its own to it

`lib/dag-layout` knows nothing about runs or documents, and every canvas is sokkel-ui-graph's:
the library measures, places and draws each one, and `components/graph` holds what they share --
the door that fetches elk for the library, the panel a view stands in, and the tools in its bar.
**The editor's graph is sokkel-ui-graph's `PipelineGraph` with `editing`, handed data and
callbacks only**: one `PipelineStep` per step of the stored document as edited -- its title by the
quartet's rule, the block it runs (or what a source listens to) as its kind, a fan-out's count,
`edited` or `not installed` as its badge, and what `lib/requirements` says it lacks as its issues
-- and every gesture ends in the same document mutations the step's pane makes. **The pipeline
page's graph is the same `PipelineGraph`, handed data and nothing else**: `shapeSteps` in
`lib/pipelines` reduces the current version's shape to one `PipelineStep` per step -- its title by
the quartet's rule, its block as its kind, what it depends on, a source's glyph and what it
listens to, and a fan-out's `each`. **A run's graph is sokkel-ui-graph's `RunGraph`, handed data and nothing else**:
`runSteps` in `lib/run-detail` reduces the pinned definition and everything the stream said to one
`RunStep` per step -- its title by the quartet's rule, the block (or a reply's `sent` / `not sent`)
as its kind, `nodeTone` as its status, its duration and progress, what it is doing as its hint, a
fan-out's count and chips or counts line, and the words its box keeps room for -- and the library
measures, places and draws it. Every graph component is lazy, and the screens share one copy of
React Flow, the version dirigent and the library resolve to together.

**Motion lives on edges, and it means data travelling.** Beside a live state's status dot, which
breathes while the state is happening, a run's graph is the one place in this app that moves, and
only while the run is live: an edge out of a step that has produced its output
into one still reading it is dashed in the ink and travels along its path, and the
moment a step produces its output every edge out of it into a step that could still read it plays
one short handover before settling. An edge stills as soon as either end is done -- a source that
failed or skipped never had an output to send, and a target that has settled is not reading one.
A node gains nothing from any of it -- status colours stay the only colour voice
there, and selection stays neutral -- so what a reader watches is where the data is, not which box
is loud. A terminal run is still everywhere, and so is one opened after it settled. Somebody who
has asked their machine for less motion gets the same reading standing still: a travelling edge is
lit in the same ink and a handover is not drawn at all, decided by the library from the setting
rather than left to a stylesheet to hide -- and `index.css` stops the animations as well, so a
frame rendered before the preference lands is still still. The library derives every edge from
the tones of its two ends (`runLink`): the tint is the source's settled state mixed 35% toward the
resting stroke, an edge into a skipped step is dashed, one out of a step that has produced into one
running travels (`data-motion="flowing"`, `lit` under reduced motion), and a step the graph saw
produce pulses each edge into a step that can still read it (`pulse`); an edge into a running step
that nothing travels is drawn a little darker. The two keyframes the library's edge names come
with sokkel-ui's base styles. A pulse is held 700ms from the handover that started it, so a live
run's stream redrawing the graph every second neither cuts it short nor restarts it.

**Layout is recomputed on the shape, not on the state.** `signatureOf` is what the elk call is
keyed on: which nodes there are, how wide and how tall each is, and what joins them, and the
library keys its own on the same. A step going from running to succeeded moves nothing, because a
run's box with a state keeps the room of a duration from the start and the room of every word in
its `reserve`; typing into a config field moves nothing either.

## A form is a JSON Schema, drawn by the library

Every generated form -- a step's config, a step's engine groups, the run dialog's parameters, a
schedule's pinned parameters, a connection's settings -- is sokkel-ui's `SchemaForm`, held by
`useSchemaForm`, through `GeneratedForm` in `components/schema`. What a field's control is, what
its bounds are and what is wrong with a value are the library's: it checks the value against the
schema with ajv, the formats `lib/schema-formats` registers among the standard ones, and says
each issue at its field with a colored edge and a mark at the end of the input. A field's issues
show once it has been left with a value or the form asked to be sent, never on open. **A verb over
a form asks the form**: pressing Run, Create or Save calls `submit()`, which shows every issue,
focuses the first that stops it, and sends nothing while one stands; `SchemaIssueCount` beside the
verb counts them. The verb is shut only for what the form cannot say, such as a role, a missing
code or a window, so the form's `blocking` never shuts one: a verb shut quietly over an issue
nobody has been shown yet says nothing about where it is.

**A form over a document is held by the document.** The step panel's forms take the step's map
as `useSchemaForm`'s `value` and write each change back through `onChange` (`DocumentForm` in
`components/schema`), so an edit in the source pane is what the form draws, and an edit the
document store refuses leaves the form as the document is.

`lib/form-schema` hands the library the schema: every `title` taken out, so the label is the key,
and each field a connection kind declares secret marked `writeOnly`. `lib/schema-form` still reads
a schema as field descriptors, for the screens that describe a schema rather than edit it: the
catalog, the pipeline pane's parameters, a step group's summary line and the step panel's list of
refusals.

**A shape the library has a control for is the library's.** A map of scalars -- headers, query
parameters, environment variables -- is its key/value rows, each key unique, the boxes named by
the map and the row (`headers key 1`, `headers value 1`) and the row's Remove by the map and the
key (`Remove headers Accept`). A union of scalars, such as a `Size`, written `16KB` or as a count of bytes, is one text
box, read as the narrowest branch the text parses as: `16KB` stays text, `16384` is a number.
A list of scalars is its list of rows.

**What no control fits is edited as JSON.** A value with no type, a union with an object or a list
among its branches, a map of objects and a list of them are a JSON buffer -- the same editor a
document is written in, in `application/json`. `drawnAs` in `lib/form-schema` reads a field the
way the library's own dispatch does, so the buffer takes exactly what the library would draw as
JSON text. Text that does not parse is held as the form's draft and said at the field, and the
form will not be sent over it.

**A field that carries a program is edited as one.** A string whose schema published a
`contentMediaType` -- `application/jq` for the three jq verbs, `text/x-shellscript` for the shell
string `shell.run` and `docker.run` take, `application/sql` for a query, `text/x-jinja` for a
report's template, `application/x-compose+yaml` for an inline compose file, `application/fhirpath`
for the FHIR pack's FHIRPath verbs, `text/cql` for its CQL library -- gets the same editor a
document is written in, through the same `CodePane`, so a jq program is read on the lines it was
written on. `GeneratedForm` hands it to `SchemaForm` as the control for that field, the label, the
help and the issue mark staying the form's. `dirigent_common.programs` is where the
seven are spelled, and the schema is what decides this and nothing else: every other string stays
one line, however long a value it holds.

Each of the seven is highlighted in its own grammar and in the theme's code inks, the
`--code-*` tokens sokkel-ui draws every highlighted block in, so a program reads the same in an
editor and in a description's code block. A name bound from outside the program -- jq's `$name`,
FHIRPath's `%name` and `$this` -- wears the variable ink, because it is the one thing a reader of
an expression has to look for elsewhere. A name written in backticks or in CQL's double quotes,
`define "Numerator"` included, is a name and not a string.

**A document is written in one editor wherever it is written.** The editor's source pane is
checked and completed against `GET /schema/document` -- a key no block takes is squiggled where
it was typed rather than reported a round trip later -- and a step config field whose schema says
it carries a program is the same editor in the program's language. The check is the library's,
and says one thing per fault: an empty `config:` is marked at the key, a value in the wrong format
says only the format it expected, a key the schema deprecates is offered last and struck through
with "deprecated" beside it, a union of a type and a `${...}` string is offered as that type
("integer or null"), and a reference to a definition with no type reads "any", never the
definition's name, so `http.request`'s `body` is "any or null". **A pane and its window are two
views of one buffer**: sokkel-ui's `useControlledDocument` holds the text as a shared document
both editors draw, kept in step with the value the page holds, so what is typed in either shows in
the other and is reported once, a value changed elsewhere replaces the text without coming back as
an edit, one undo history serves both, and closing the window loses nothing.

**A pane too small for what it holds opens in a window, and the button is at the top.** sokkel-ui's
`WindowedPane` is where that gesture is written once -- the button, its place, and the window, which
is the viewport less a margin -- and every pane that offers one comes through it: a config field
carrying a program, a value edited as JSON, a report document, an alert body, an example's source,
the block of produced JSON on a run's step, a schema's page, the pipeline source pane, and the graph
on a run's page and a pipeline's. Its words come from `windowWords(name)` in `lib/design-system`:
the button says "Open <name> in a window", and the window's close says "Close the window". **The
pane stays in place while its window is open** (`keepPane`): the window draws its own copy, an
editor's over the same shared document, so nothing on the page moves and the pane shows every edit
made in the window. **A program's window carries its language's reference beside the editor**
(`aside`), split and resizable, and stacked under it on a narrow window. **A pane in a panel with a
head hands the button to the head**, beside the panel's other tools: the pane wraps the whole panel
with `button="none"`, draws the panel only where it is the pane, and the head carries
`WindowedPaneButton` at `size="icon-sm"`, the size of a head's other tools. **A pane with no head keeps the button over its own top-right corner**, shown
while the pointer is over the pane or focus is in it and always on touch; a pane that grows with a
long document holds it to the top of whatever scrolls it (`button="sticky"`), so the button is on
screen wherever the reader has scrolled to. A block of produced JSON is the exception: its lines
run to the edge and scroll sideways, so it sets `WindowedPaneButton` in a column of its own at the
box's right edge, always shown, and no line runs under it. A panel clips its corners with `overflow: clip` rather
than `hidden` for this reason: a hidden overflow is a scroller of its own, and a button held to it
would never move. Reference material in a pane is set inset (`frame="inset"`).

**The side panel's toggle is at the screen's right edge.** While the panel is shut it is the last
control in the top bar; while it is open it is the last control in the panel's own strip, over the
panel it shuts. The rail's own collapse is beside the logo.

**A field that names a thing shows the thing.** A string property carrying `x-dirigent-ref` holds
the code of a connection or a schema, and under the box -- the issue mark staying on the box -- the form draws what that code resolves to,
in the step panel's own group gesture: a shut row with a one-line summary, and the definition under
it against the group rule when it is opened. A schema the document carries in its top-level
`schemas:` resolves before one the instance holds, which is the order the engine resolves them in,
and says `carried by this document`{ .label }; one the instance holds says `instance` and opens with a link
to `/schemas/<code>`, a connection with its kind, its health as every screen draws it, and a link to `/connections/<code>`. A
code nothing holds is `not stored`{ .label } or `not configured`{ .label }, muted, and not a button -- there is nothing
under it to open. Nothing is called missing while the listing behind the answer is still being
read, and a value written `${...}` names no code at all, so neither draws a row. The code itself is
never repeated: the box above the row already holds it.

**A JSON Schema is edited against its own meta-schema.** The media type
`application/schema+json` is what asks for it: a buffer holding a schema document is checked
against JSON Schema 2020-12, the draft the server validates with, so its keywords complete as
they are typed and a value the draft does not take is marked where it was written. Two buffers
hold one -- the dialog a schema is written in, and the schema's own page at `/schemas/<code>`,
where a stored one is corrected beside a value it is tried against -- so a shape is fixed in the
editor it was authored in rather than read in one place and rewritten in another. What that page
may change is what `SchemaUpdate` carries: the name, the description and the body. The `code` is the heading and never a box, because the route addresses the schema by it
and every `validate.schema` step and `requires.schemas` entry names it.

**The label is the key.** What is being edited is a document, and the word an author writes in it
is `max_response` rather than "Max Response", so `lib/form-schema` takes every `title` out and the
library labels the field by its key in mono. `description` is the help under the label, and whether a
field is required is said beside the label rather than inside it, so the control's accessible
name stays the key. **The required word is in the muted ink, never amber**: amber is the brand's
and the focus ring's, and a field label is neither. `SchemaForm` draws it with
`requiredMark="word"`, and the control says it is required with `aria-required`. **A default is
shown and never written.** A field left unset shows its schema `default` muted in the control,
`GET (default)`, and the form's value leaves the key out, so what is sent carries only what was
chosen and the server applies the rest. An optional choice with a default offers `Default (GET)`
first, which takes the key out again once something else was chosen. The default is also said under the control (`fallbacks`),
as what applies when it is left empty; a `default` of `null` says nothing there.

**Every field is a design-system control, and an empty one looks like an empty one.** A field
renders through `ui/input`, `ui/textarea`, `ui/select` or `ui/switch` and never a bare element,
and the treatment is checked in both palettes: the dark one fills a rung of the ladder and edges
it with a hairline the ground shows, and the light one has to say the same thing with a fill and
a stronger line, or a value floats in whitespace and an empty box is not there at all. A row is
the key as its label, the annotation beside it, the control, and one muted line under. **A secret
is the library's `SecretField`**, in the library's words: an unset one is an empty masked input with Show; one the
connection already holds is sealed -- masked, saying it is set, with Replace, named by its field
("Replace basic_password") so two sealed secrets are told apart -- and stays out of what is sent
until it is replaced, so the server keeps what it has. Never the words "not set" as
prose where a control belongs.

**A section the document requires is open, and one it does not is a link.** A run dialog asks for
a window because the document it runs reads one -- a step writing `${run.window.start}` stops the
run it is given none in -- so where the document references it the section stands open, every field
in it is required, and the verb is shut with the sentence saying what is missing. Where the document
references none, the same fields sit behind one plain link and nothing is asked. A dialog that hid a
field the document cannot run without would have the server refuse what the form could have asked
for; one that opened every optional section would make every dialog the longest form it could ever
be.

**A form draws every field its schema publishes**, in the schema's order, required and
optional alike; a short field takes half a row where the form is wide enough. **What is needed is
in front, and the rest is one disclosure** where a form stands among other things: a step's config
and a carried connection's row in the apply review open on the fields the schema requires and the
ones already set, and the rest wait behind the library's `N more fields` (`fold`), which opens by
itself while a folded field has an issue to show. Which fields are folded is decided when the form
is first drawn, so a key being filled in does not jump under the hands typing it; another step is
another form, and opens folded again. A dialog that is the asking itself -- Run, a trigger, a
connection -- folds nothing.

**A value written as a reference is not checked against the field it stands in.** The document
language lets `${...}` stand wherever a value goes, and what one stands for has no text, no bounds
and no type until the run resolves it, so a field carrying one is checked for nothing else --
not its pattern, not its enum, not even that it is a number. That is the rule the server applies:
`defer_references` swaps every such value for a sentinel that every JSON Schema keyword passes
over, so a form that refused one would be refusing a document that applies. What counts as one is
`hasReference` in `lib/references` and it is the engine's own grammar: a run of dollars before
braces with something in them, the dollars collapsing in pairs, so `$${...}` is a literal and
`${}` is text. It holds where a document is being edited and nowhere else -- a step's config, and
not its clocks or its retry budget, which are the engine's own keys -- because a run's parameters
and a connection's config are values, and the server checks those literally. Whether the reference
names something the run will have is the whole document's question, and Validate is what asks it.
The source pane holds to the same rule from the other end: `GET /schema/document` publishes each
block's config with the reference beside every field's own type, so the two halves of the editor
agree about one document.
The form is told so with `deferred`, which `useSchemaForm` leaves unchecked: `deferReference` in
`lib/form-schema`. **A control that cannot hold a reference gives way to a box**: a number, a
choice and a switch each draw a value the schema describes, and drawn by their own control a
reference would read as empty, unset or off and the first touch would write that over the
document. So `GeneratedForm` draws the text in a mono box, says beside the label what the box
stands in for (`a reference, not a choice`{ .label }), and clearing the box brings the control
back. The same holds for an object, a list or a map written whole as a reference. A union of
scalars is already a text box and holds one as it is.

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

**A pipeline that does not exist yet is edited in the same screen.** `/pipelines/$new` is the
editor with no pipeline behind it: the local document is a skeleton nothing has applied, so
everything in it is editable, the code among it. Validate is the same dry run against the draft;
Run is shut, because `$run` runs the version the instance holds and there is not one. The first
apply creates the pipeline and the screen goes to the address it will answer at from then on --
which is why a static `pipelines/$new` route sits beside the dynamic `pipelines/:code`, and why
`New` is the primary half of the listing's split button while the two doors for a document
written somewhere else, `From a template…`{ .label } and `From a file…`{ .label }, are in the menu beside it.

**A document opens on the source that holds it.** The editor's panel opens on the step tab,
because a pipeline is read a step at a time, and choosing a box on the canvas opens that tab
rather than whichever one was last in front of somebody. The exception is a document that arrived
as text: `From a file…`{ .label } on the listing hands the editor what it read and `From a template…`{ .label } hands
it the copy it made, and the editor opens on the source pane, which is where that document
actually is. A blank `/pipelines/$new` opens on the step tab like every other screen -- the canvas
says how to add the first step, and the source, whose schema would mark an empty `steps` map
before anything had been done, is a tab away.

**The step panel reads the config first, then the engine, then the name.** What a step does is the
block's own config, so the panel opens on that form. The
engine's half sits under it as five groups in one order -- Waits for, Fan-out, Timing, Retry, Rule
-- because `for_each`, the timings and a retry policy are the setting a step runs in rather than
the question it answers, and a flat list of twelve controls buried the two keys the step was about.
A shut group is one row: its title, and a mono line of what would run, with the values the document
sets in body ink and the defaults it leaves alone in muted -- `timeout 30s · no deadline ·
on_timeout fail`, `off` for a fan-out over nothing, `all_success` for a step that says nothing about
its rule, the prerequisite keys as chips. Clicking the row opens that group's own fields under
itself, against one rule in the identity colour marking what is being edited; the line goes while
the row stands open, because the fields under it say the same thing, and a group holding a
refusal stands open with no button to shut it, because a refusal folded away is one nobody can
answer. `poll` belongs to a sensor, so the timing group neither says nor draws one for an operator
unless the step carries it anyway. Which key belongs to which group, and how each line reads, is
`lib/step-groups` over the schema in `lib/step-keys`, so a member added to the definition is filed
rather than appended to a list. The display name is last and it is one small field: nothing
references it, and asking for it first was asking the least of the step first.

**Apply is quiet until it would write.** The button takes the identity colour where the document
differs from the version the instance holds, and where there is no version at all; where applying
would write nothing it stands in outline beside Validate, which is what it would do: the
`primary` item's `variant` is `outline` then. A run's Rerun is outline the same way while the run
can still move.

**A plan says what an apply takes away before it is pressed.** The dry run answers with the source
rows and the managed schedules a document has stopped declaring, and those are the one consequence
in the dialog that cannot be read back from the document: a source goes with its inputs and its
token. The plan is two of sokkel-ui's `ConsequenceList`s: what applying changes is the `neutral`
one, and what it removes is the `critical` one under it, each a row per kind with its count and
its codes in mono, and each drawn only where it has rows. `lib/pipeline-plan` decides the rows;
`PlanReading` is the one renderer, for Validate and Apply alike. **An update shows the document it
writes over.** Under the lists, sokkel-ui's `DiffView` sets the stored document against the one
being applied, both rendered the way the source pane renders them, headed by the two versions and
by a count of each side that changed. In the dialog it opens on its changes: unchanged runs more
than three lines from a change fold into a row that opens on a press, and the window button sits
in the diff's own header, after the counts. It declares no height, because folding is what keeps
it short and the dialog's verbs stand in a footer its body scrolls under, so a cap would only put
a second scroll inside the first. The window draws every line, with no title of its own, since
the window's title names the document: its counts float at the top end rather than take a row. Where the two render the same nothing is drawn -- not a diff saying "No changes" --
and the plan's own line says it once. What an apply did to its sources and schedules is the note that follows
it. **A token an apply created is shown once, the way a rotated one is**, because the answer to that
apply is the only time it can be read: `MintedToken` stands over the editor before anything moves on.

**A refusal the dialog can answer is answered in the dialog.** A top-level `connections:` or
`schemas:` section is what lets a document run alone under `dg run --local`, and an apply refuses
one that carries either -- a refusal that stays, because a reference by code is the single
contract and a stored document that carried a credential would carry it into every version and
every export. What stood beside that refusal was a Cancel and an Apply that could never work, and
the remedy the sentence named was a command line, so the way forward is under it now.
`lib/carried` is the decision and `components/pipeline/CarriedOffer` lays it out: one line saying
what an instance stores and what applying does, then every carried entry with its kind, its code
and what becomes of it. **The server's own refusal is not drawn beside it.** A message is
rendered by the CLI, by this screen and by every other client, so it states the fact and names no
tool; printing it over a list and the controls that answer it would put one fact on screen three
times with the least actionable copy loudest. `lib/starters.uncarry` is what lifts the sections
into `requires:` -- the same text rewrite `dg pipeline new` makes, so the teaching comments
around everything that stays survive it -- and the button says `Apply`, because a button says
what somebody wants and not the steps behind it.

**Four cases, and the row says which.** A carried entry meets an instance that has nothing under
that code (`create`), one holding the same thing (`already here`{ .label }), or one holding something else
under the same name (`differs`); the fourth is a document that only names a code under
`requires:`, which carries nothing to create from and is what the plan's own issues and the
Requires chips say. **Applying never replaces a stored schema.** A stored schema is what every
other pipeline naming that code checks against, from its next run, so an apply that wrote over
one would change what those pipelines check without anybody having decided that -- and the line
over the list, which counts what applying stores, would stop being true. `differs` shuts the
confirm and the sentence beside the rows says which code collided.

**So `differs` is the row's own decision, and it opens in the row like every other.** What stood
beside it was a sentence naming two remedies, both of them the document author's: change what the
document carries, or carry it under a code of its own. The third -- update the stored schema to
what the document carries -- is the right one often enough that leaving it out made the dialog a
dead end, and it was the one thing the browser could not do at all. So the row expands over what
the instance holds, in the pane a schema is read in everywhere else and at a pane's height, with
the window for the whole of it; says that every pipeline naming that code checks against the new
shape from its next run, which is what a run pinning its shapes at creation actually means --
and, under the names, that a run in flight keeps the shape it started with, which is the half a
reader mid-run needs; and offers the write. It is a write of its own and not a step of the
apply, because the two answer to different people -- one pipeline's author is applying, and
every other pipeline naming that code lives with the result. **The identity travels with the
body**: storing a schema reads its own `title` and `description` where the write names neither and
`PATCH /schemas/{code}` reads nothing, so a replacement sends all three or the instance keeps the
labels of a shape it no longer holds. The row then reads `already here`{ .label } and the confirm is drawn,
the collision it was shut for having gone -- and that is the whole report, in the place the reader
is already looking.

**A carried schema is stored and a carried connection is not.** A schema is a shape: it holds no
credential, and storing it under the code the document already names puts the same resource where
an instance keeps one -- under that code and no other, because it is what every `validate.schema`
step in the document references and nothing here invents or renames it. A connection's config can
hold a credential in a field the kind declares secret and in one it does not, since a `sql` or a
`git` connection's `url` carries a password or a token inline, so nothing can read a carried
connection and say no credential is in it; nor can it be compared with a stored one, because a
read redacts every secret field. It is named under `requires:` and the way forward is the form
that mints one -- never a sentence telling somebody where to go while a button goes there.

**And that form opens in the row that said so, because leaving this screen costs the document.**
A pipeline nothing has applied is held in `lib/pipeline-document` and nowhere else, and the
editor forgets it as it unmounts, so a link out of this dialog was a control that destroyed the
work it was offered to rescue -- which is the same fault as a confirm that cannot confirm, read
from the other end. The row expands under itself instead, the gesture below for a row whose verb
needs a form, and nothing navigates. **The code and the kind are the document's own**, the row
already draws both, and no box asks for either again: a create under a different code would
leave the row exactly as it was, and the code is never on a screen twice. What the form asks for
is the credential -- the kind's settings, a secret field for each it declares secret -- because
**nothing is read out of the carried connection**, which is the whole reason a connection is not
created from a document. A kind this instance has not installed publishes no config schema, so
that row offers no form at all and says `missing` alone. The instance is asked again the moment
the credential exists, which turns the row `already here`{ .label } and is what was in the way of the
confirm being drawn; nothing says it a second time as a line or a toast. A remedy that has to
send somebody to another screen belongs on a document the instance already holds a version of,
and there is no such remedy in this dialog.

**What a copy of a template still needs is said where the copy lands.** A copy rewrites the two
lines that make it somebody's own and leaves what the document carries in it, because the apply
is what refuses a carried section and the dialog it raises is where the shapes in it can still be
stored; a copy that lifted them first would name schemas nothing holds, and an apply refuses that
too. The editor draws what is still missing as chips under Requires -- `lib/requirements` checks
connections and schemas alike against listings the screen has already read, and claims nothing of
a listing that has not landed.

**The source pane may hold text that is not a document**, and while it does, the local document is
the last one that parsed and nothing else may write to it. A form quietly replacing text somebody
is halfway through fixing is worse than a form that says it cannot.

**The source pane holds the text it was handed, then renders the document.** A document that
arrived as text -- a picked file, a template's copy, something typed into the pane -- is shown in
that text, comments and blank lines and all, until a structural edit moves past it; from the first
edit on the canvas or in the step form, the pane renders the local document, because no renderer
can put a comment back. `GET /pipelines/{code}/$export` stays the canonical text: it orders steps
topologically and keys the way a digest is taken over, while the pane renders the document in the
order it is held in, so what is edited and what is read back are the same thing. An apply
canonicalises it.

**The editor's schema comes from the instance.** `GET /schema/document` answers with
`dirigent/v1` composed with this instance's own block config schemas, one `if`/`then` case per
installed block, so the editor marks a config key the named block does not take at the character
it was typed at, and completes a step's `config` from the block it names. Every value position in
a config also takes a `${...}` reference as an alternative, which is where the server defers one,
so a reference is never marked. An instance with a plugin another lacks answers with a different schema, which is
the point: the editor refuses exactly what that instance's apply would.
**A refusal is marked once, where it is.** Where a value fails every branch of a choice -- the
document's pipeline or triggers, a block's `if`/`then` case -- the library reports only the branch
that fits it, the one whose `kind` or other constant matches, else the one with the fewest errors,
so a key a block does not take marks that key and nothing around it: not `format`, `kind`, the
step's name or its `params`.

**dirigent's own formats are checked by the server's rules.** `lib/schema-formats` registers them
with the library's `registerSchemaFormats` once, in `main.tsx`, for every schema check the library makes:
`humane-duration` and `size` as the server parses them, `ulid`, `uuid4`, `uuid7`, the hex digests
and `base64` as its format checker reads them, and `storage-uri` as any string, because the schemes
are this instance's backends' and only an apply knows them. A value that fails one says what was
expected in the words a field's hint uses, `LABELS.form.format` -- "Expected a duration such as 30s
or 5m", "Expected a version 7 UUID" -- never the format's name. A format nobody registered, such as
a pack's, is not checked and says nothing.

## The palette is a registry

`src/lib/palette.ts` holds actions as data: `id`, `title`, `group`, `keywords`, `hint`, `run`.

The shell registers what is always there -- every screen the account is offered, the view rows,
sign out. A screen registers what only it can do, from an effect, and returns the unregister so a
row cannot outlive the screen that would carry it out. Re-registering an id replaces the row.

The settings dialog is the same idea for a different surface: `src/lib/settings.ts` holds every row
as a record -- what it is called, which category it is filed under, what else it can be found by --
and the shortcut rows are derived from `lib/shortcuts` rather than written down twice.
**The dialog is sokkel-ui's `SettingsDialog`**: `settingsGroups` hands it the rows as its groups,
sections and settings, and the library draws the nav, the search across every category, the rows,
the phone's list to go into and the footer with its note and `Done`{ .label }. What a row puts on
it -- its control, and whether that control trails the title or sits under it -- is
`components/settings/SettingsDialog.tsx`'s, keyed by the row's id: a choice from a set and a pair
of buttons trail, the palette's cards and an open password form sit under. The dialog opens on the
category the thing that opened it is about, the server dot's on Server, and a phone then opens on
that section rather than on the list. Its words are `SETTINGS_WORDS` in `lib/design-system`, and its
search box says `Search`{ .label } like every other.

**General holds the behaviour preferences**, each one a store the screens read rather than a
copy this dialog keeps: which clock every timestamp is read against, whether a log pane opens
following its tail, and whether an editor marks the row the caret is on (`CodeEditor`'s
`activeLine`, off by default, in every editor and its window, read-only ones included: a
read-only editor takes focus on a click or Tab, so it is a tab stop and shows its caret's row). A preference defaults
to what this app did before it existed, so nothing moves under a reader who has never opened
this dialog, and an editor already on screen takes the change without being rebuilt.

**Its nav reads Preferences, You, This instance**: General, Theme and Shortcuts are preferences,
Account is the reader's, and Server is the instance's. There is no About, because a version stated
on two panes of one dialog is the same fact twice; the documentation and the API reference are two
links on the Server pane's last row, `Reference`{ .label }, where the instance they answer for is and
where the search finds them. A refused read of what the instance is states the refusal once, in
the Server section's `foot`, under its rows. **A pane carries a line under its heading only where it
says something no row can** -- Shortcuts says where the keys work, in its section's `lead` -- **and
almost no row carries one under its label.** The search box's placeholder is "Search" and its
accessible name, `words.searchLabel`, says what it searches. A row's `description` is
optional and survives only by adding a fact the control cannot show, such as which timestamps a
clock setting moves and which keep their own -- so a line restating the label is not written.

The registry is drawn by sokkel-ui's `CommandPalette`, which the shell holds: `paletteGroups` hands
it the shelves, and it matches with `filter="terms"` rather than by fuzzy letters, because a fuzzy
match would put a screen's own name below whichever row shares more letters with the query. Every
term must match, so typing more words narrows; a title that starts with the query sorts above one
that merely contains it. A pasted run or attempt id is the palette's search: `idResults` answers it
with the one row that opens it.

**Every chord this app binds is a letter.** On a Norwegian layout `[`, `]`, `{`, `}`, `|` and `\`
all need Alt to reach at all, so a binding over one of them is a binding nobody here can press.
The platform's modifier plus K opens the palette and `?` opens the list of every key, both bound by
the shell; the platform's own modifier plus B hides and shows the rail, and `T` shows and hides a
run's terminal -- each matched as the character it produced, never as Shift plus a physical key.
`src/lib/shortcuts.ts` decides the two this app binds itself as pure functions, and
`hooks/use-app-shortcuts.ts` is the one place it reads a real `KeyboardEvent`. The shortcuts dialog
is the shell's: the keys the shell and the screens bind with sokkel-ui's `useShortcuts`, then
`shortcuts()` for the rest, under one heading.

## Panels are sized in pixels

**The rail is dragged by its right edge, and opens at 168px.** It holds between 152px, where
its longest word still fits, and 320px. What it was dragged to is kept in pixels per browser, a
double-click on the edge gives it back its 168px, and the edge is sokkel-ui's `ResizeHandle`, a
`separator`: it takes the arrow keys, Home and End, and says what it resizes. The control at the
rail's head narrows it to its marks and its edge pulled outward widens it again, which is kept
too. Hiding it whole is the platform's modifier plus B and `Show navigation`; a hidden rail has no
edge. Below the breakpoint the rail is a drawer and is not dragged. The rail's width, whether it is
narrowed and whether it is hidden, and the right panel's width and whether it stands open, are what
`lib/panels` keeps, each read out of storage as its store is built, so the shell renders at its
settled size on the first paint rather than snapping into it.

**What is in the right panel is the screen's.** The panel itself is drawn once, sokkel-ui's
`SidePanel` in the shell, and a screen fills it with `fillPanel` from an effect that returns the
unregister -- the same shape as registering palette actions, and for the same reason: a panel
cannot outlive the screen whose data it is drawing. A tab is an id, a label, an optional mark and
a `render`, and the open tab is remembered by id in `lib/panels`, so a screen that gains a tab does
not move the reader onto a different one. **The tabs are a real tablist** with the content as its
tabpanel, labelled by the tab shown, and the arrows, Home and End move between them. A panel of one
tab still draws it as a tab (`soleTab="tab"`), because a screen's tabs come and go and the header
must not change shape with them. A screen that fills nothing has no panel and no toggle.

**Whether the panel stands open is the reader's; a screen opens it for one visit.** The toggle is
the only thing that writes the stored preference. A selection, or an address that names a row,
opens the panel through `openPanel` for that screen alone, and the next screen starts from the
preference, so a link into one screen never decides how every other screen first draws.

**The status line carries the screen's two facts.** `lib/screen-status` holds one note and one
identifier, stated for as long as a screen is mounted -- where a run's event stream is, and the
trace the run is on. The note is data with a tone rather than markup, so what a connecting stream
says is a pure function, and sokkel-ui's `StatusLine` draws it one line tall whatever it holds: a
live note with its pulsing dot, the identifier in mono, and the version the instance runs at its
end.

The right panel is dragged, and what is stored is **pixels, not a fraction**. What somebody
dragged it to was a decision about the content in it -- wide enough for a log line, narrow enough
to leave the table readable -- and a fraction re-decides that every time the window is resized. A
window narrower than the stored width clamps for that session and leaves the stored number alone,
so the intent comes back with the window. The drag handle is a `separator` and answers the arrow
keys, because a panel that can only be sized by pointer is a panel some people cannot size.

**The rail's and the panel's edges are sokkel-ui's `ResizeHandle`; the run terminal's top edge is
`hooks/use-drag-size`.** Either way the pointer is followed on the document rather than on the
handle, and the size is written to the element's own style while the drag lasts -- a React render
per pointer event leaves the edge visibly behind the hand -- with the store hearing the committed
number.

## The shell is sokkel-ui's

The frame is sokkel-ui's `Shell`: the rail on the left, the top bar over the content, the content
as the one thing that scrolls, the right panel as a column where a screen fills one, and a status
line along the foot. **The rail, the top bar and the panel's tab strip stand on `--sidebar`, and
every strip in the top row is one height** -- `h-shell-top`, the library's -- so the rail's head,
the crumb and the tabs sit on one line. `e2e/shell.spec.ts` measures every strip with
`getBoundingClientRect`, in both palettes, with the rail hidden and the panel open.

**The rail is the mark, the screens and the account, top to bottom**, sokkel-ui's `Rail`. Its head
is the brand tile and the word `dirigent`, which is the way to the dashboard, and the control that
narrows it. Its entries are each a mark and a single-line word, and a word that names a screen
needs no gloss under it. **They are grouped by what somebody is there to do**: Dashboard alone at
the head; Operate (Runs, Triggers); Build (Pipelines, Connections, Schemas); Reference (Blocks,
Examples); and, for an admin, Admin (Users, Workers, Alerting, Audit). `railGroups` in `lib/nav`
is what the rail draws, from the array the palette offers, and the line an entry carries about
itself is data the palette reads and the rail does not draw. Narrowed, the rail is the marks alone,
each naming itself in a tooltip; the shell narrows it on its own while the panel stands open on a
window under 1280px.

**The account stands in the window's bottom-left corner, at the start of the status line**, and
the whole row is the control: sokkel-ui's `AccountMenu`, its avatar the username's first letter,
the username beside it, and the account's role muted after that (`detail`), a plain word as a role
is everywhere. The username keeps its room: on a row narrower than 13rem, the rail's own 168px
included, the role leaves the row and is said only in the menu's head. **This is the one place a
code stands in the UI face.** The username is the account's code, and wherever it is addressed -- the accounts listing, the Account pane, a
token's owner -- it is mono; here it is the reader's own name said back to them. The menu opens
upward: its head is the username and the role with the instance's name and environment under it, then
Settings, Keyboard shortcuts with `?`, the mode as System, Light and Dark, in the Theme pane's order, with the one in force
checked, and Sign out.

**The rail hides whole.** The platform's modifier plus B and the palette's row take it off screen
and bring it back, and while it is hidden the top bar's menu button opens it as the drawer at
every width. Whether it is hidden is the reader's, and kept.

**The top bar is the screen's crumb and the instance's corner**, sokkel-ui's `TopBar` with
`trailEnds="ancestor"`. At its left stands the crumb: where a screen is one thing, the trail back
to the listing it belongs to -- the screens above it only, every step a link and none of them
marked as the page, because the page's own heading names it. A screen states its trail with
`ScreenTrail` (or a `PageHeader`'s `trail`) into `lib/trail` for as long as it is mounted, and the
bar draws it, so the page opens on its heading. A listing has no crumb. At the right, the palette's
button, the library's: the search glyph, the word `Search`{ .label } and the chord; the instance's
dot; and the panel's toggle in the window's corner, where the screen has filled a panel.

**The status line is the screen's, and the version's.** The screen's note at its left, in its
tone, and at its right the screen's identifier and the version this instance runs. Nothing a
screen states there is something its own page already says -- how many rows were read is the
table's -- and an instant is the house's relative form. A settled stream says nothing.

**A page's head stands still and its body scrolls.** Under the top bar a page is two parts: the
head -- the title, the code under it, a line of facts and the screen's verbs, which `PageHeader`
and `PageHead` draw into the shell's head slot -- and the body, which is the one scroller. So the
track starts below the verbs, never beside them. The scroller spans the content column to the
window's edge with the page's padding inside it, and its thin track, in the line tokens, sits in the
right margin that padding leaves: it takes no width the content had, nothing moves sideways when it
appears, and the body and a docked terminal end at one right edge, the same edge as the head.

**A fact appears once in the shell.** How this instance is doing belongs to the dot, and nothing
true of the session rather than of the screen stands beside the crumb.

**The dot is the whole of what it says while the instance is well**, sokkel-ui's `ServerMenu`,
`quiet`. Its accessible name is the instance's name from `/system/info`, the version and the
state. Its tooltip is headed by the name, the environment (`environment`) and the version, with
when it was last asked under them (`checkedAt`), and lists every check with its own dot, state
and detail; opening it asks again (`recheck`) unless an ask is already in flight.
**Words appear only when something is wrong**: `Server degraded`{ .label }, `Server unhealthy`{ .label }, `Server unreachable, retrying`{ .label }, beside the dot.
`SERVER_STATES` in `lib/server-status` is the map of states it is drawn from, and the dot pulses
while the instance is still being asked. It re-asks on a slow clock, when the tab comes back, and as
its tooltip opens. A press opens the settings dialog's Server pane (`onPress`), which is what a finger has where there
is nothing to hover with, and where the checks' times and the Recheck button are.

## Small screens

The shell has one breakpoint, `md` at 768px, and one rule above it: at `md` and up nothing about
the shell on this page changes. Everything below is what the same screens become on a phone.
**Nothing scrolls sideways.** A page whose body scrolls horizontally is a defect, whatever is in
it, and so is a listing that scrolls inside its own card.

**A listing has no breakpoint of its own: it follows the width it was given.** The window cannot
answer for a listing whose box it does not know -- the same columns fit a 1024px window and
overflow the moment a panel takes half of what was left. So the card form is the listing's own
answer about its own box: `DataTable` measures the box it is drawn in, and `LISTING` has it stack
its rows once that box is narrower than `lg` (`stackBelow: '64rem'`) and narrower than the least
its columns take, never under 36rem (`minWidth`). A listing beside an open panel draws cards while
the window around it is as wide as it ever was; at 1024 with the rail open and no panel, every
listing is a table.

**A utility hides; `useSmallScreen` chooses.** `md:hidden` on one of two renderings leaves both
in the document -- every row and every control twice, two elements with one accessible name --
so where the same content is drawn two ways, the hook is what decides and only one is built. A
class is still the answer for hiding a thing that has no second form.

**The rail becomes a drawer**, the shell's. Below `md` it is off screen until a menu button at
the left of the top bar -- icon only, `aria-label` "Open navigation" -- opens it over a scrim,
drawn expanded. It closes by its own close button, by Escape, by a tap on the scrim, and on every
route change, because a drawer still standing over the screen somebody navigated to is a drawer
they have to dismiss twice. Focus moves into it on open and back to the button on close. The
account menu lives at its foot.

**A listing row becomes a card where the table will not fit**, which on a phone is every
listing. `DataTable` draws a narrow list as one row per record: its first column as the row's
title, and every other column on a line after its column's name. A title that is a name with its
code is `stackTitle: 'free'`: its cell reads `stacked` from `useTableCell` and draws `ItemHeading`
stacked (a run's `PipelineRef` is already name over code), so the code has a line of its own under
the name and is never cut. Any other title is one line. A column headed by
nothing is a control -- New token, Revoke -- and takes its line without a name, at the edge the
facts start from. What a row does as a table it does here: a row that opens a panel opens it, and
a row that is a link is one. An account's tokens stack the same way under its row.

**A column with nothing in it for that row is left out of the card, label and all -- and the
cell is what says so, by returning `null`.** A component that renders nothing is an element all
the same, so a cell handing one back reads as a fact the row has, and the card draws a label
with a blank beside it: a schema with no description under a `Description` saying nothing. The
column decides, never the component it draws -- a tag strip with no tags, a duration for a run
still going, a description that is empty are the cell's answer and not the component's.

**The breadcrumb is the way back**: below `md` only the last screen above this one stands, after
a chevron pointing back, and it truncates with an ellipsis rather than wrapping the strip onto a
second line. A crumb that is a code is in mono.

**A toolbar does not wrap, here or anywhere.** A screen's verbs are data rather than markup --
sokkel-ui's `ToolbarItem`s, in a `PageHeader`'s `items` or a `Toolbar`'s -- measured against the
room the strip leaves them, so the primary action keeps its place while the verbs before it move,
from the last, into one overflow menu, `aria-label` "More actions", without a label being written
down twice. The primary stands after the items and More and never folds: the library's `primary`,
the same shape, filled. **The strip draws its verbs by their words alone** (`wordsOnly`); the menu
lists each with its mark and its full label. The editor's strip is one row at every width
(`nowrap`): the document's code is cut short with the whole of it on hover, and the verbs fold.

**A dialog is a sheet.** Full width, full height, its footer pinned to the foot and its body the
part that scrolls. It is the generated dialog's own slots that are restyled in `index.css`, not
a second dialog.

**The right panel opens from the foot.** Below `lg` the shell draws it as a sheet sliding over
the screen from the right, raised by its toggle; below `md` the shell's `panelStrip` puts the
panel's tabs in a strip at the foot, a tablist named `Side panel`{ .label } with tabs a finger
tall: a tab raises the sheet on itself, another switches it, and the open tab, Escape or a press
on the dim lowers it -- so the graph screens are the graph, and what is beside them is a tap
away. The sheet's header then names the tab shown. A screen that fills no panel has no strip.

**A document is read, not written, below `md`.** The source pane is read-only, the add-step and
delete-step controls are not drawn, and neither is any of the three verbs -- Apply, Run, and the
Validate that would dry-run a document nothing here can change. The strip says "Read only on a
small screen" where the verbs were, and carries the document's identity and nothing else: what
version it is at is in the status line already, and a fact appears once on a screen. A graph is still
read, a step is still chosen, and a run is still watched.

**A segmented control that does not fit wraps; it never becomes a menu.** The control is for a
set somebody can see all of, so the set stays on the screen below the breakpoint too: one
standing at a form field's height is a grid two cells wide there -- four options are two rows of
two, an odd last one takes the width -- and the single row it always was at `md` and up. A label
too wide for its cell wraps onto a second line, because a cut word says less than a folded one.
Folding the control into a picker instead would hide behind a press exactly what it exists to
show.

**Every control a finger lands on is at least 44px tall, whatever element it is made of.**
The height is one token, `--spacing-finger`, and below the breakpoint every control takes its
minimum from it. sokkel-ui sizes its own: buttons but the extra-small sizes, toggles, inputs,
input groups, both selects, the combobox, `SearchField` and `FilterChip`, and icon buttons as
wide -- so a listing's bar is a finger tall throughout. `index.css`
grows the rest against the generated primitives' slots: a tab, a menu's or a tooltip's trigger
not drawn through a `Button`, a command input, menu, command and combobox rows, and
`control-link`, which is what a link drawn as a control wears: a drawer entry, a chip on a
header strip, a row that navigates. The canvas's zoom cluster and the window's
`GraphViewButtons` are sized there as well, being the graph library's buttons rather than ours. A menu opened at a point rather than under a
control -- the canvas's right-click menus -- anchors a zero-sized trigger at the cursor, and
`data-menu-anchor` keeps the rule off that one, because nothing draws it and no finger lands on
it. A bare status dot is its own tooltip's trigger and is not grown: it keeps its own `dot` slot
over the trigger's, so it stays one line tall, which a graph node's 15px row needs. Where a component draws a control of its own it is `h-finger` or `min-h-finger`. A control
drawn as a square takes the width too, because a 44px tall target 28px wide is a target on one
axis only. No screen sizes a control for a phone itself.

**Text inside content is not a control.** A card's title link, a timestamp, the link in a
heading and a tag chip a row wears are the row's words rather than something drawn to be
pressed; they keep the size the type scale gives them, and the row holding them is what the
finger has -- which is `min-h-finger` already. The rule is about what the app draws as a
control, and that is what makes it checkable.

**A keyboard chord is drawn only where a keyboard is likely.** The palette button is the search
glyph at every width, with Cmd/Ctrl+K on its tooltip rather than on its face, because a phone has
no modifier key to press and a chord on the strip says nothing to a pointer; below the breakpoint
it takes the square the finger rule gives an icon button. The list of shortcuts keeps its keys,
being a list about keyboards.

## A kind may be drawn as well as named

**A glyph that identifies a kind is information, not decoration.** The one decorative element in
this app is the login graph and that does not bend: a mark earns its place here by telling kinds
apart at a glance, which a column of identical dots and four words cannot do. So a kind may carry
a mark of its own, and only a kind may. A glyph never stands for a state, and one drawn beside a
word that already says the same thing is the decoration the rule above forbids.

**A glyph belongs to a kind, and `lib/glyphs` is the one place a kind is given one.** A
connection kind and a notifier are the same word -- `slack` names the credential's kind and the
sender alike -- so there is one map and one function over it, `kindGlyph`, pure over the code the
wire answers with. Adding a kind is adding one entry there and nothing else: no screen keeps a
table of its own, and no screen works a mark out from a code itself.

**The mark is drawn beside the code wherever a kind says what a thing is.** The channel strip's
chips, a rule's target, the connections listing's row, the connection's own dialog, the New
connection dialog's kind rows, the pipeline editor's reference row under a field naming a
connection, and the health rows on the home screen: a reader who learned the envelope on the
strip reads it on all seven. A screen that says what a thing is and draws no mark is the fault
this rule exists to stop, because the same kind looking different from one screen to the next is
the reader's problem rather than the screen's. The blocks catalog is the one screen that names
kinds and draws none: its rows are the registries themselves, where the kind is the row rather
than what the row is, and it lists schemes and notifiers in the same shape beside them.

**The mark does not take the kind's word away.** Where the kind is said -- the connections
listing's row and the connection's dialog, as the mark and the kind in mono, with no hue, because
status is the only colour those two carry -- the word stays beside the mark: it is the value
somebody types into a document, and a mark cannot be typed. Where it is not said the mark stands with the code
alone and the kind is not spelled twice: a channel chip and a rule's target are the mark and the
code and nothing else. The dialog's kind rows and the editor's reference row spell it as well,
for the reason the picker's rows do -- the kind is half of what the row is found by, and the
reference row has no code of its own to stand beside, the box above it already holding one.

**A pack declares the mark its own kind wears, and it is one path or it is nothing.** A
`ConnectionKind` carries `mark`: the `d` of a single SVG path on the same 24-unit grid, which
reaches the app through the catalog and is held once in `lib/marks`. `kindGlyph(kind, marks)` is
still the one place the question is answered -- the built-in map wins for the kinds it names, a
declared path is drawn next, and the neutral glyph is what is left -- so a screen still asks one
function and keeps no table. A declared path is a string off the wire, so it is drawn only when
it is path data and nothing else: non-empty, ASCII, path-data characters, at most 4 kB, which is
what registration held the pack to and what this bundle checks again before a browser sees it. A
notifier declares none, so the channel strip and a rule's target draw the marks this bundle
names.

**A kind with no glyph takes the neutral glyph rather than a gap**, which is the same one a
palette row with no icon takes. Kinds arrive from whichever packs an instance installed, so a
pack's kind that declares no mark of its own gets a mark rather than a hole beside the kinds this
bundle was built knowing. Something that is not a kind at all carries neither a mark nor a
neutral one: a worker row on the health panel holds the mark's width so the codes under it line
up, and draws nothing in it.

**Two kinds that are the same sort of thing may share that sort's mark.** `kafka` and `rabbitmq`
are both queues and both wear the queue; the code is always beside the mark, and it is the code
that says which of the two is in front of somebody.

**The glyph says what a thing is and the dot says how it is, and neither does the other's job.**
A glyph never takes a status colour and a dot never says which kind something is, so a card
carrying both says two facts rather than one loud one.

**What the kinds this repository ships wear**: an envelope for `email`, a scroll for `log`, the
Slack mark for `slack`, a webhook for `webhook`, a globe for `http`, a branch for `git`, a
database for `sql`, a container for `docker`, a drive for `s3` -- a mark says
what the credential opens and an s3 one opens storage, where a cloud would say where a thing is
hosted, which half this list could claim -- and an ordered list for `kafka` and `rabbitmq`. A
glyph is `size-4` in muted ink wherever it is drawn; what it sits in belongs to the thing drawing
it -- the palette row gives it a `size-7` tile on `--muted`, a channel chip draws it bare.

**lucide draws every glyph that is not a brand, and a brand mark comes from the brand.** lucide
ships no brand icons at all. A brand mark is Simple Icons' where it carries one and the brand's own
media kit's where it does not -- Slack is the second case, so its mark is the paths off
`slack.com/media-kit`, kept inline in `src/components/alerting/SlackMark.tsx`, the shape untouched
and scaled onto the same 24-unit grid every other glyph is drawn on. **A brand mark is monochrome
here**, which is what a kit's monochrome variant is for: it takes the surface's ink in both
palettes like everything else on the strip, where a mark in its own colours would be the loudest
thing on a screen whose colour means a state. A mark a pack declares is held to the same two
rules: one path on the 24 grid, filled in `currentColor`.

## The channel strip

**The strip is one wrapping line of chips, and a chip holds three things, and a fourth when
something is wrong.** The kind's glyph at
16px in muted ink, the code in mono, and an 8px dot: 36px tall, on the control's rung, on the card's ground
with the app's own border. A credential that failed or has proved nothing says so after the dot,
in `healthOf`'s word; a healthy one, the log and a kind nothing is set up for say nothing. Nothing
else is on it -- no time, no sentence -- because a paragraph per channel is a screenful of channels
on a screen whose subject is rules.

**A connection is a channel and a notifier is a kind**, so a chip says the connection's code and
the glyph says the kind: five email credentials are five envelope chips reading `ops-mail`,
`billing-mail`, and so on. Only a kind nothing is set up for is one chip reading the notifier's
own code, and so is the log channel, which has no credential to name.

**The dot has three colours and no more.** Green where the channel can deliver -- the log
notifier, or a connection whose last check passed. Red where the last check failed. Grey for
everything else: a kind nothing is set up for, a credential nobody has checked, a probe that
proved nothing. A reader learns three colours once; six would be a legend.

**The rest of the words are the tooltip's, and a credential's are the connections listing's**: `healthy`,
`failed`, `not verified`{ .label } and `never checked`{ .label } are `healthOf`'s, read through it rather than said a
second way here, so one credential reads the same wherever it is drawn. The strip adds two of its
own, for the two things that are not a credential: `ready` for the log channel, which nothing
checks, and `not set up`{ .label } for an installed notifier no credential exists for. The tooltip is this
app's own primitive, it opens on hover and on keyboard focus alike, and it holds, in this order:
the kind and the state word (`email · failed`), how long ago the check was where there was one,
the connection's code in mono, and the check's own sentence in full. Nothing on the strip ever
says "connection" or "built in": a reader knows they have not set up Slack, not that a credential
of kind `slack` is absent.

**A chip goes where its channel is.** One with a credential opens it at `/connections/<code>`;
a grey chip with no credential opens `/connections?new=<kind>`, which is the connections screen
with its dialog already on that kind; the log chip goes nowhere, because there is nothing behind
it to open.

**Every chip answers a pointer and the keyboard the same way, the log chip included.** It takes
the row wash, the focus ring every control here takes, and its tooltip on hover, on focus and on
a click alike -- the log chip is a button rather than a link, and nothing else about it differs.
A chip drawn inert beside its neighbours would be saying it is a different kind of thing.

**The strip is ordered by the dots**: green, then red, then grey, and inside one colour the
notifier's code and then the connection's. A notifier's chips stand together only where their
dots agree -- the channel that stopped is what the strip is read for. `channelsOf` answers in
that order, so no screen decides it.

**Below `md` the heading is the fold, and it carries the answer.** A chevron, the word Channels,
and at the right one dot per channel in the same colours and the same order, nothing else. It is
folded on every visit: what a phone is on this screen for is the rules and the queue. Opened, it
is a table of three columns -- the dot; the glyph and the code; and either `Set up <notifier>`
for a grey chip with no credential or how long ago the check was -- and a row with a credential
is a link to it, like the chip.

## An option wears what its value wears

A dropdown whose options are values the app already draws somewhere -- a status, a kind --
renders each option as that drawing: the status filter's rows are the same chips the listing
shows (`FilterOption.row`), and the chip carries the one it chose as its `value`. Choosing becomes recognising. An option
never wraps; the menu grows to its longest row instead of folding a label in half.

**The menu is floored at its control and capped at the screen.** It is never narrower than the
control it hangs from, so a menu is at least as wide as the thing that opened it; it is never
wider than its longest row needs, nor than the screen less a 16px gutter at each edge. It hangs
from the control's start edge, swaps to the end edge where starting there would put it off
screen, and slides along where neither edge fits -- so a menu never scrolls sideways and never
hangs off the screen. Only where the longest row is wider than that cap does a row give way, and
then it is the label that ellipses.

**A string option is drawn bare, and every other value wears its JSON.** A generated form's enum
is words a document carries -- `GET`, `all_success` -- so the row and the trigger read `GET`, not
`"GET"`; a number, a boolean and null are drawn as the JSON they are, which is what keeps `2` and
`"2"` two choices in an enum holding both. The quoted spelling is the token a select addresses a
choice by and it is never on screen: the trigger draws the option, not the token.

**A choice between looks is made on the looks themselves.** Where the values of a setting are
appearances -- the three palettes -- the control is sokkel-ui's `ThemeCards`, one card per value
showing that value, and the cards are a radio group: one tab stop for the group, entered at the
chosen card, the arrows moving and choosing in one gesture, and the library's ring and check on the
chosen card. A card is drawn from the tokens it stands for and never from a colour written down
beside it.

## A surface is inset once, and 16px is the inset

**Every surface this app draws -- a dialog, a card, a panel pane -- holds its content 16px in
from its own edge, and the generated primitives already say so**: `DialogContent` is `p-4` and
`Card` is `py-4` with `px-4` on its content. So a surface writes no padding of its own. A `py-2`
or a `py-8` laid over a card is a second answer to a question the card has already answered, and
the three states of `PageState` proved it: the same card carried 24px of vertical padding while
reading, 24px when empty and 48px when refused, for no reason anybody could state.

**A surface that lays out its own body zeroes the primitive's padding and spends the same 16px
itself.** The command palette is the one: a search row, a scrolling list and a footer rather than
a form, so `index.css` states the inset once as `--palette-inset` and every part of the dialog
stands on it -- the search glyph, a shelf heading, a row's icon tile, the footer's key chips.
A strip that crosses the whole width (the generated footer's `-mx-4 p-4`, the palette's search
row and footer) takes the inset back inside itself, so the seam runs edge to edge and the words
still land on the edge. A strip's height is the inset above and below what it holds, which is
what makes a 24px line of search text a 56px row.

**Half the inset is the only other number, and it is the gutter a floating box gets.** A list of
rounded rows needs room or the highlight touches the surface's sides, so the list is padded 8px
and each row is padded 8px again: the wash is inset 8, its content lands on the 16 like
everything else. A box nested inside a surface that is already inset takes the same 8 --
`Refusal` inside a form or a dialog is `p-2`, not a second 16.

**A surface scrolls; a block inside it does not.** A dialog above the breakpoint has no height
of its own, so one that outgrows a short screen is capped at `max-h-[calc(100vh-4rem)]`, laid
out as a column, and its body is the part that scrolls -- the header and the verbs stay where
somebody reaches for them, which is the same arrangement `index.css` gives every dialog below
the breakpoint. A block that caps itself instead puts a second scroll inside the first and cuts
its own content off at a line nothing drew: a settings group capped at `40vh` hid the last
password box under its own fold, and what was on screen was a label with no control beneath it.
So the three tall dialogs -- a new rule, a new connection, and an apply whose offer opens a form
in a row -- cap the surface and scroll the body, and nothing between the header and the footer
declares a height.

**A preview of what already exists is the one exception, and it takes a pane's height.** A
surface that asks for a decision has to draw the thing being decided about -- the schema this
instance holds, under the sentences saying what replacing it would do -- and that reference
material has no length of its own. Given its own height it grows until the sentences and the
controls that act on it are below the fold: the apply dialog's `differs` row drew a 283-line
shape as 5110px of pane and left its own Cancel and confirm 4904px past the foot of the dialog's
scroller, and even a sixteen-line shape with ten dependants left them 98px past it. A reader must
never have to go looking for the control the surface is asking them to press. So a preview
declares a height and scrolls inside itself, which is what holds the sentences and the controls
still, and the whole of it stays one press away in the window every pane offers.

**The height is the one that leaves the controls on screen, and it is measured.** It is a pane's
height rather than a share of the viewport -- `max-h-40` on the block of JSON in that row, nine
lines, which is what the dialog's own cap leaves on a 768px screen once the sentences have had
their room. What it is measured against is the scroller the controls sit in, found by walking up
from the control: compared against the dialog's own box a clipped control reads as visible, which
is how this got past two rounds of review.

**A preview, and nothing else.** The exception covers read-only reference material -- a block of
JSON, a stored body, the definition a field's code resolves to -- and it does not reach a form, a
field, or anything else with a control inside it. That is the fault the rule was written for: a
settings group capped at `40vh` hid the last password box under its own fold, and what was on
screen was a label with no control beneath it. Everything else between a header and a footer
still declares no height -- and it came back in three dialogs at once, each in that same shape:
the run dialog capped the parameter form it wrapped at `50vh`, the new source capped its sample
at `32vh` and the new schedule its pinned parameters at the same, every one of them
inside a surface that declared no height of its own. So two of the three stood taller than a
768px window with nothing to scroll, and the third hid 1372px of its own form under a fold
nothing drew. **A share of the viewport named anywhere but on the surface is the tell**, and it
is what a scan can read.

**A preview's height is the block's, not its callers'.** Where one component draws every preview
of a kind -- `JsonBlock` is the block of JSON everywhere -- the height is stated there once, so a
call site cannot leave it off and two call sites cannot disagree about it. A surface with less
room to give narrows it from outside and says what it measured, which is what the apply dialog's
carried row does; a surface with more room does not widen it, because the window is where the
whole of a thing is read.

## A row expands under itself rather than opening a second dialog

Where a row's verb needs a form -- changing a password on the settings dialog, minting the
connection an apply's carried offer says this instance has not got -- the form opens in that
row's own place, under it: its fields on one line, and Cancel beside the verb, right aligned at
its foot. A dialog raised over a dialog puts a scrim over the thing it is about, and the row that
offered the verb is already the sentence saying what the form is for. The button that opened it
is replaced by the section while it stands, so there are never two controls that shut it, and the
refusal is `Refusal` inside the section, where the fields it is about are. **One row at a time**:
two open forms in one list are two half-typed things with one confirm behind them. **The exception
is the connection dialog and the account dialog**, which are one dialog being tried and not a
second one: Edit is the same surface, and the only thing ever raised over one is the `ConfirmDialog`
every verb that takes something away goes through.

**What the row already says, the form does not ask.** The row is the summary, so a box repeating
a value drawn a line above it draws that value twice and offers to change something the row's own
case depends on. A form that stands inside another decision opens on what is required and folds
the rest, because the list the row belongs to has to stay on screen beside it.

**A form reached this way is the same form it is anywhere else.** Its state, what it sends and
why its confirm is shut live in one place that both surfaces read -- `lib/connection-draft` and
`hooks/use-connection-draft` under `ConnectionFields`, drawn by the New connection dialog and by
that row -- because a second copy of a form is a second set of rules about what a blank box
means, and one of the two will be the one with the credential in it.

The step panel's engine groups are the same gesture at rest: the row is the group's own summary,
and its fields open under it rather than in a pane of their own.

**An account's tokens are listed under its row.** A token authenticates as one account, so it is
filed there rather than in a second table with an Account column. They are the row's `detail` in
`DataTable`: the table's own chevron at the head of the row opens and shuts it, named and tooltipped
`Show the tokens of <account>` or `Hide the tokens of <account>` by `expandLabel`, and does nothing else, and the right and left arrows do the same on the row
the arrows reached; pressing the rest of the row opens the account's dialog, and the heading's own
tooltip says so. Several accounts may stand open. What opens is a `DataTable` list of its own, set
under the row and reading `GET /users/{username}/tokens` when it is opened and not before. It keeps
a cursor of its own, asks for the next page as its rows near their end, and is capped at 24rem with
its heads stuck, so an account holding hundreds does not push every other account off the page. A
closed row says how many live tokens it holds, from one read of `GET /tokens`, and says nothing at
all where that read did not reach the end, because a number off part of a listing is not a count.
An account with none draws `No tokens.`{ .label } when opened, with no heads over it and no count
under it. **`New token`{ .label } is on the row**, so a token is never made for the
wrong account, and the row opens to show what it made.

**A token row is its name, the three times it has, and Revoke.** There is no Prefix column: the name
is what a token is known by. The prefix is drawn beside the name only when two live tokens of one
account share that name, which is the one time the name stops telling them apart, and its tooltip
says what it is. The expiry is a chip beside the name, only where a token has one; `Last used`{ .label } and
`Created`{ .label } are columns. **Revoking asks first, and takes the one token the row is.** The API
revokes by id, so a row's own Revoke reaches that row and no other. The question names the token the
way the row does: its name, and its prefix beside the name where two live tokens share it.

## A control only ever claims what the situation supports

Three faults are one fault: a button labelled with its mechanism rather than its outcome, a
heading that enumerates a column the rows already carry, and a confirm that cannot confirm. Each
is a control asserting something that is not there. **What a control says and offers is what the
situation can actually give**, and everything below is that rule applied.

**A dialog that asks is a decision, and a decision needs both paths.** A way back, and a way
forward that does something. Where the forward path does not exist, the control that would open
the dialog is shut and says why, and no dialog opens: the pipeline editor's Apply is shut on a
document that is already the version the instance holds, because a dialog whose own answer is
that its button would write nothing is friction with a question mark on it. Where there is
nothing to decide -- the outcome is certain and harmless -- the action happens and reports
itself in one line, the way every other action that completed without incident does.

**A footer has one dismissal word, and it is `Cancel`.** A dialog that asks carries `Cancel` and
its confirm, and nothing else in its footer. A dialog that only tells carries no footer at all: it
is dismissed by the corner's close and by Escape, so no footer ever says `Close`, `Done` or
`Dismiss`. sokkel-ui's `DialogShell` is that rule written once -- `confirm` given, the footer and no
corner close; `confirm` absent, the corner close and no footer. **A dialog that reads one thing is the
third case**, and it is a connection's: the corner close, and a footer of `actions` on that thing
rather than a confirm, so nothing in it says Cancel because nothing has been started. **A dialog that asks
and then tells changes case when it has answered**: a token made, whose secret it now shows, and a
test message sent, whose delivery it now reads, take the corner close from that moment, because
nothing is left that a Cancel could take back.

**One dismissal, one control.** A dialog whose footer carries the way out does not also draw the
corner's own -- `showCloseButton={false}` -- because two ways out of one dialog are two answers to
one question, and a reader counting controls is counting wrong.

**A confirm is drawn only where pressing it would do something.** A plan the instance would
refuse, a carried code that collides with what the instance holds, a connection nobody has
created: in each the apply cannot proceed, so the button is absent and the sentence beside the
rows is what says why. **The exception is a control shut by who somebody is**, which stays drawn
and shut with its reason, because that is a courtesy about the account rather than a claim about
the document -- and it is how somebody learns the verb exists and is not theirs. **A run's verbs
are the second exception** while the run is unsettled: what it allows changes under the reader as
it moves, so Pause, Resume, Cancel and Rerun keep their places and are shut there with the reason.
A settled run has stopped moving, and draws Rerun alone, as the run screen says below.

**A shut control looks shut.** It drops its fill for a hairline ring on no ground, its word goes to
the muted ink at weight 400, and the pointer over it is `not-allowed` -- so a shut verb beside an
open one is never read as the quieter of two open ones.

**A form that is not filled in yet is not this rule.** A confirm shut because a required box is
empty, because a write is in flight, or because the reader has not typed what the kind asks for,
is a forward path that exists and is not ready -- it stays drawn and shut, and filling the form
opens it. What is not drawn is a confirm whose outcome the situation cannot produce however long
somebody sits in front of it.

**A shut control stays reachable.** `disabled` takes a control out of the tab order and stops it
taking a pointer, so the sentence saying why is readable by nobody on a keyboard and by nobody
hovering the control itself. A verb on a screen's strip is shut with `aria-disabled` instead:
assistive technology hears the same thing, the control keeps its place in the tab order, the
reason is its tooltip, reachable both ways: a `ToolbarItem` or a sokkel-ui `Button` given a
`reason` is shut this way, and a shut verb folded into the menu carries its reason as a line under
its entry.

## A write that can be refused says so, and a shut control says why

**Every write states its refusal, and there are two places to state one.** A dialog or a form
has room beside the thing that was refused, and that is `components/Refusal`; a row's button and
a panel's verb have none, and that is `sayRefusal`, the one toast this app raises about a
request. A write whose rejection handler is a comment saying the row keeps what it had is a
write that failed in silence. **Nothing dismisses on a refusal**: a dialog that closed and a
panel that emptied would both have said the request went through.

**The refusal is read from the problem document, not from the status.** `Problem.title` is the
status phrase this server sets it to, so a dialog headed by it says "Unprocessable Content" on
every refusal it can make; `problems` is the list behind the sentence. `lib/refusal` is where
that is decided once -- including that a `detail` which is only its own `problems` joined is
drawn as the list alone rather than as the same sentence twice.

**A refusal is drawn in this interface's words, not in the ones the server sent.** A refusal
arrives with a dotted code, the params its sentence was written out of, and that sentence
already rendered into `detail` by whichever Python process minted it. The code and the params
are the translatable pair, so what is drawn is `LABELS.refused[code]` written out of the params;
`detail` is drawn only where neither this table nor the instance's contributed one holds a
sentence. Drawing `detail` by preference is how a translated interface ends up saying translated
chrome around an English refusal. A pack's codes are not in `labels.ts` -- this bundle cannot
know which packs are installed -- so `lib/wording` reads those once from `GET /labels`, and a
read that fails leaves every refusal on the fallback, which is what was drawn before it landed.
`scripts/check_refusal_labels.py` is what keeps the fallback from quietly becoming the rule
again.

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
trigger. The primitives are sokkel-ui's, so what this app wants of them is said in `index.css`
against their slots, or added to the library.

## A graph fits what it draws

**A node is 44 tall, two lines, and as wide as its words, on every canvas.** The title in mono, and
under it the block it runs, with the key in front where the title is a name. **No key is ever
cut**: before elk sees a box, its lines are measured in the face the node sets them in -- on a
canvas of its own, in the loaded font, read off the characters until the faces have loaded -- with
every glyph, mark, count and dot that stands on that line, and elk is handed the widest plus the
box's chrome, between a floor of 96px and a cap of 280px: sokkel-ui-graph's `graphNodeSize`, on
every canvas. Only past the cap does a word truncate, and it carries its whole value on hover. **The editor's box
keeps room for both its badges and its issue mark before it wears any** (`reserveBadges` with
`edited` and `not installed`, and `reserveIssue`), so the first keystroke into a step, or the
catalog landing, moves no box. `not installed` is critical and wins over `edited`, which is
neutral; the badge says the word and nothing more, and the sentence naming the block that is
missing is the step's issue, so it is said once, the box takes the critical edge, and its mark opens
what is wrong. A box is filled in `--node`, edged
in a line a step above the canvas, and lifted by a shadow of its own; a status is the only colour
on it -- a succeeded box takes the succeeded edge, a failed one the failed edge at 1.5px over a
wash of the same hue, a skipped one a dashed edge on no fill -- and a chosen box is ringed in the
foreground, which is no colour at all. A document's config is a map of any size and one
truncated line of it crowds the box, so the step's own pane holds the whole of it. A step whose
`for_each` fans it out says so in the neutral ink, because a status is the only colour a node
carries: a stacked glyph (`ICONS.fan_out`) and the count, or the word "each" where the list is an
expression a run resolves, at the end of the title line -- sokkel-ui-graph's `countIcon` with
`countPlacement` `title`, on the pipeline page's canvas and in the editor alike -- with what
`for_each` does on pointing at it (`countTitle`) and nowhere else. On a run the state's dot stands at the end of
the title line, and the duration at the end of the second. **What a step is doing -- what it waits
for, how a retry went, why it failed -- is the box's tooltip and the panel's, not a third line**,
because a line nobody can read at 11px across 138 pixels says less than the colour of the box. A
run's fan-out holds its elements in a strip beneath the two lines, and **an element's key wraps
rather than truncates**: the chips widen the box up to 240px and then wrap, each line adding 18px
to the box. A retrying element's chip keeps the room of its widest countdown (the chip's own
`reserve`, `try 99 in 999s`), so a countdown does not widen the box every second. Past `ITEM_STRIP_LIMIT` elements the strip counts
them on one line. Before a grid read from a step's output has expanded, that strip is the words
`waits for <step>`. Elk is told the height each is actually drawn at, or the rows come out spaced
for a box that is not there.

**Every word on a box carries its whole value on hover.** A title, a key and a block each carry
their full value on their own `title`, with what the step is doing after it on a run.

**A source says what it listens to where a block would be.** A step with `source:` runs no block, so
its second line is what it listens to and its title leads with `ICONS.source`, on a dashed box. In
the editor that is the instance's own reading of the source -- `listensTo`, `POST /endpoints/signups`
or what a polled kind says of itself -- and the document's `kind` until an apply has made one. On
the pipeline's page and a run it is the kind, which is what the pinned graph carries, and pointing at that line says it
whole after "Listens to" (the box's `lineHint`). A reply says `reply`{ .label } there, on the editor's canvas
and its step panel as on a run. A step that is none of the three says `no block`{ .label }.


**A canvas on a page is as tall as its drawing, or as tall as the room the run screen leaves it.**
The pipeline's page draws the graph in sokkel-ui-graph's `fitted` frame, a box whose height follows
the layout's own proportions at the zoom the width allows, so a five-step chain is a strip and not a stage with a strip floating in
it. The run's page is a column whose graph takes every pixel between the heading and the docked
terminal -- less the failure panel, where there is one -- so there is no dead ground under a small
graph, and dragging the terminal's seam is a resize the canvas refits to. It is sokkel-ui-graph's
`filled` frame with `fillFloor` 240: never shorter than its drawing or 240px, whichever is less,
and a drawing taller than the room it is given is fitted at the floor and panned. The canvas itself is transparent and draws no dots;
the graph panel's own body is the ground and the dot grid under it. The editor keeps a stage,
because it is a workspace somebody adds to.

**A canvas on a page pans and zooms; a plain wheel is the page's unless the canvas is the
screen.** Dragging the ground pans every canvas. A pinch, and a wheel with Ctrl or the platform's
modifier held, zooms a canvas on a page about the pointer, each event held to one
`WHEEL_ZOOM_LIMIT` step, so a mouse wheel's notch is a step and a pinch follows the fingers. On the
pipeline's page, whose canvas is as tall as its drawing and has panels under it, a wheel with
neither scrolls the page, so a long page never traps it. On the run's page the canvas is the
screen and there is nothing to scroll past it, so each notch of a plain wheel zooms it one zoom
button's step about the pointer, and the page under it never scrolls; a pinch, or a wheel with
Ctrl or Cmd held, zooms it smoothly. A trackpad's two-finger scroll is a plain wheel to the browser
and cannot be told reliably from a mouse's, so on the run's canvas it zooms too, a burst within
160ms counting as one notch; the ground is dragged to pan. Below the breakpoint a finger on either
page's canvas scrolls the page, and the graph's window is where it is panned. Each page's zoom
buttons say how else to zoom on their tooltips, and nothing is drawn over the graph to say it.

**A view's layout is the reader's for the visit.** The run's graph and the pipeline page's carry a
`Layout`{ .label } control: the direction (left to right, or top to bottom), the edges and the
spacing. Both are sokkel-ui-graph's `GraphLayoutMenu` (`components/graph/ViewTools`'s
`LayoutButton`), whose order of spacings (compact, normal, roomy) and width are the library's, with
`routings` limited to orthogonal and splines, opened by an `IconButton` on `ICONS.graph_layout`,
its tooltip saying `Layout`{ .label }, handed in as the menu's `trigger`, and closed by a choice
(`closeOnChoice`). **Both open on elk's orthogonal routes around the boxes** and offer elk's splines
beside them; the editor draws those orthogonal routes, left to right, and offers nothing else. A
routed or curved edge is drawn along the points elk answered, with each edge into a step arriving
on its own rather than merged into a trunk. Both views are laid out in the direction chosen at
every width, never turned on its own on a narrow screen. The choice is held by the screen and nowhere else -- not in
storage, not in the address -- so the next screen, and the next visit, open on the default. The
editor has no such control, because a document's arrangement there is the author's.

**A view opens in a window.** The window's button stands in the canvas panel's head, after the
layout control. The window is a stage: the wheel zooms, the ground pans, and it carries the zoom,
the fit and the layout, which is the same choice as the page's, as one cluster over the window's
top right corner: zoom in, zoom out,
fit and the layout, the same buttons the page's head carries. A box chosen in the
window is chosen on the page -- the address and the panel follow it -- and the window stays open
until it is dismissed.

Every canvas opens with the whole DAG in view: `fitView` with padding, held between two bounds --
sokkel-ui-graph's on every canvas (padding 0.12, and each graph hands it `fitMinZoom` 0.8). The
pipeline page's and a run's hand it `narrowFit` as well, so their floor is 0.8 on a canvas 560px
wide or wider; the editor's hands it `narrowFit={false}`, so its floor is 0.8 at every width.
**On the pipeline page's or a run's canvas narrower than 560px -- a phone -- a fit goes under that
floor to fit the drawing's width, to 0.6 and no lower**, because there a finger on the canvas
scrolls the page and nothing pans it, so a drawing hanging off the right edge could not be reached
on the page. A graph is read at 0.6 there rather than cut; the window is where it is read larger.
**A run's drawing that fits across and is only a little too tall goes under that
floor, to `tallFit` 0.7 and no lower**, so a graph a few pixels taller than the room above the
terminal is seen whole rather than hung off its foot; a drawing too wide keeps the floor. A run's
fit frames the bends of its edges as well as its boxes, so an edge that runs round a row stays on
the canvas. The upper bound is 1 on every canvas, so a fit never draws a box above its
own size and a pipeline of two boxes is not magnified to fill the space, and the floor keeps a
12px title and an 11px word legible. **Past that floor the graph is not shrunk: it stays at the floor,
hangs off the canvas, and is panned.** A view too wide or too tall for the canvas opens with the
start of the graph at the top left and the rest off the far edges, because a graph is read from its
first steps and a centred one has both ends cut, and dragging the ground is how the rest is reached.
Zooming further out is still there by hand, down to the library's `MIN_ZOOM` (0.25) on every
canvas, and that view is the reader's. It re-fits when the node set changes,
when the reader changes the layout, and when the canvas is resized -- the right panel opening and
the terminal's seam moving are resizes, a page scrolling is not -- and stops the moment the reader
pans, zooms or drags a box: after that the view is theirs, and the fit control, or Re-layout in the
editor, is how they hand it back. On a run's graph a zoom press takes the view over as a pan
does. A press that moves nothing, on the ground or on a run's box, is not a pan. On every canvas
a layout chosen after the reader moved the view fits it again, and a resize of a view the reader
took over brings the chosen box back onto the canvas, at their zoom, if the resize cut it. The
browser suite asserts every node's box lies inside the canvas for a graph that fits at the floor.

**A deep graph is wrapped onto rows rather than drawn as one**, on every canvas.
Seventeen steps in one left-to-right row is three thousand pixels of canvas, and a fit answers that
by putting a node's text under six pixels. Past `WRAP_WIDTH` -- which `rankDepth` measures a shape
against before elk sees it -- elk is asked to cut the layering into chunks and stack them: the
ranks still read left to right, and the height nothing was using carries the rest. The run's graph
and the pipeline page's are wrapped to their canvas (`wrapToCanvas`): the room is the canvas's width at
`fitMinZoom` -- at the narrow fit's 0.6 on a canvas narrower than 560px -- and its height at the lower
of that and `tallFit`, and no row is wider than the same 1120px, handed as `wrapWidth`. A
graph whose own elk layout, edge bends counted, fits across that room stays one row; otherwise elk
lays it out once in the room's shape, and the library keeps whichever of the whole graph and the
cut fits the room at the larger zoom, so a cut that only adds height is not drawn. The pipeline
page's canvas is as tall as its drawing, so it has no height to give, and its graph is cut by the
room's width alone. That holds in the window as on the page. The editor's graph is wrapped at
`WRAP_WIDTH` alone, not to its canvas, so the panel opening beside it never lays a document out
again under somebody's pointer. A row still wider than the canvas hangs off it at the floor and is
panned.

**A zoom press is one step, and the fit button is the fit every other fit is.** React Flow's own
step by a fixed twenty percent, which on a graph read at half size is four presses to nothing. On
every canvas the library's step (1.4) is one press either way, and the fit button is its own fit.
A canvas with nothing on it has nothing to zoom, so it draws none of them. **On the pipeline's page
and the run's they stand in the graph panel's bar** -- zoom in, zoom out, fit, layout, then the
window -- rather than over a drawing: the canvas draws no buttons of its
own (`controls={false}`) and hands its zoom and fit out through `onControls`, and the head's
`IconButton`s press them, their tooltips saying how else the canvas zooms there. The window's
corner carries the same four in the same order as sokkel-ui-graph's flush cluster,
`GraphViewButtons`, with the layout menu's trigger a `GraphControlButton` in it. **The editor is a
stage, and carries the library's own cluster in its corner** -- zoom in, zoom out, fit -- with
`Add step` after them in the same cluster (`extraControls`, a `GraphControlButton`). An empty
editor draws no zoom buttons and keeps `Add step` in the corner; its words say it has no steps, and
under them, on a document nothing has applied, stands `From a template…`{ .label } (`emptyAction`).

## The canvas edits

**A graph is a view until it is handed `editing`.** The editor hands sokkel-ui-graph's
`PipelineGraph` its gestures -- draw an edge, delete one, delete a box, let a box go, drop a
connection on empty ground, right-click a box or the ground -- and each is reported, never applied
by the canvas: the document changes only through the callbacks, and the graph draws the result.
Only an editing canvas shows its boxes' handles as ports, visible and connectable. Below the
breakpoint the editor hands it no `editing`, so a phone reads the document and changes nothing.
The pipeline page's `PipelineGraph` is handed no `editing` and is a view. **The run's graph is a view by
construction**: sokkel-ui-graph's `RunGraph` takes no editing, so a step is selectable there and
nothing else, because what it draws already happened and no verb would change it. Its boxes keep
the anchors and show none, and the browser suite asserts that.

**An edge is a `depends_on` entry, and it is one edit however it was made.** Dragging between
two ports and choosing a step from the chips in its own pane end in the same `withDependsOn`
against the same local document, so the editor's strip counts a drawn edge with everything else
unapplied and nothing is written until an apply. `lib/graph-edits` is that seam: `withEdge` and
`withoutEdge` answer with the document they were given when it already says what was asked, so
drawing an edge twice is a gesture rather than an edit. A selected edge and the Delete key take
one away, and so does a selected step -- `withoutStep` takes its name out of every other step's
`depends_on` in the same edit, because a `depends_on` naming a step the document no longer
declares is what an apply refuses. Only one thing on the canvas is chosen at a time, or one press
of the key would take two away. React Flow answers neither key while the focus is in a text box,
so a Backspace meant for a config field is never a step.

**A loop is refused before it is drawn, and the refusal names it.** sokkel-ui-graph's `cyclePath`
walks the steps' own edges and answers the shortest loop the new edge would close -- `parse → active →
report → parse` -- which the canvas says beside the pointer while the connection is drawn over the
box it would close it on (`canConnect`), and the toast says again when it is let go there
(`onRefuse`). A prerequisite chosen in the step's pane is checked by `cycleThrough` in
`lib/graph-edits`, which answers the same loop without loading the canvas. `$apply` refuses the same document; a canvas
that accepted the gesture would have answered a pointer with a round trip.

**elk places a graph; a reader places a box.** A dragged position is that pipeline's own, kept
in `lib/canvas-layout` under `dirigent.layout.{pipeline}` as px-intent, exactly as the right
panel's width is -- what somebody dragged a box to was a decision about that pipeline's shape,
and it survives a reload. The graph is handed those as its `positions`, and a box let go is kept
there (`onMove`). A step nobody has moved keeps elk's suggestion, which is what a step added to an
arranged canvas gets. Re-layout clears the arrangement and fits the view to what elk decides
afresh.

**A step is added from one picker, wherever the asking started.** It is sokkel-ui-graph's
`BlockPicker` held over the canvas in a `GraphOverlay`, which opens beside the place it was asked
from, turns to the side with room, and stays inside the canvas. A right-click on empty ground opens
it at the pointer -- on a document with no steps as much as on a drawn one -- `Add step` opens it
beside itself and closes it again, the palette opens it over the canvas's middle, and a connection let go over empty
ground is "and then this": it opens where it was dropped, a dashed line runs to it from the step it
came from, its heading says which step the new one will wait for, and the step lands there. A
right-click on a box opens that box's own menu instead: one more step after this one, which is the
same picker with the edge already decided, and this one taken out. Escape or a press outside closes
it.

**The picker is grouped the way the catalog is, and searched the way the palette is.** The blocks
are listed under the groups they themselves declare, which is what the Blocks screen shelves by, so
the picker invents no filing of its own and `map.jq` and `transform.jq` sit in one group. Each row
is titled by the block's id with its summary under it. A sensor sits in its group like anything
else and wears the badge saying so, whose tooltip says what a sensor does, because a badge on every
row would say what the absence of one already says. The search field is named `Search blocks`, its
placeholder says what it searches, and the list is named `Blocks`. Typing narrows the list to what matches, each group keeping its heading, every term
narrowing and `sensor` and `operator` matching by kind; the arrows walk the rows and the return key
places one. The first Escape clears the box and the second closes the picker. While the catalog is
still being read the picker says so, and the return key places nothing. `lib/add-step` maps the
catalog to the picker's blocks and groups as pure functions, so what a group holds and what a
search finds are decided in Node.

**The key is derived, not asked for.** A menu that places a step on one keystroke cannot stop
to ask what to call it, so `transform.jq` lands as `jq` and the next one as `jq_2`, and the
step's own pane is where it is renamed -- alongside everything else about it.

## The run screen

**What failed, why, and in which step lands above the fold.** The heading is the pipeline's title
with its code and the run's instant in mono under it; one line under that says the status word,
the step it ended at, how long it took and who started it; then the graph, filling the room down to the terminal.
Under the graph a run that did not end well stands its failure panel across the width -- the step
in mono, the block, the catalogued code, the sentence the step failed with, the connection the step
named with its health where it named one, and the parameters the run was given -- and the terminal
opens at the foot with every line the run wrote. At 1440 by 900 the failure starts above the fold.
A run that ended well has no failure to stand. Choosing a box on the graph narrows the terminal to
that step and opens it in the panel.

**A run's verbs stand in one place while the run can still move.** While a run is unsettled, Pause,
Resume, Cancel and Rerun are drawn at the right of the heading, in that order, and a verb the run's
state does not allow -- Pause on a paused run, Resume on a running one, Rerun on either -- is shut
in place with `aria-disabled` and its reason on hover and on focus, because the run's state changes
under the reader and a row that grew and shrank with it is a row nobody can learn. **A settled run
draws Rerun alone**, as the primary: it will never be paused, resumed or cancelled again, and three
shut verbs that no state of it will ever open are controls claiming what it cannot give. Cancel
takes the critical wash while it is open.

**The chosen step is the address.** Choosing a box sets the address to `/runs/<run id>/<step>`,
and that address loaded chooses the step and opens its panel; the ground, or closing the panel,
puts it down and the address goes back to `/runs/<run id>`. A fan-out's element and a try of the
chosen step ride in the query as `?item=<run item id>` and `?attempt=<attempt id>`, drawn open and
marked and brought into view, and they are dropped when another step is chosen; `?tab=` is kept.
Every move between steps replaces the address rather than adding one, so Back leaves the run. An
address naming a step the run does not have opens the run with nothing chosen and one line saying
so. `lib/step-address` is that, for the run and for the pipeline's page alike.

**A try and an element carry their ids.** Each attempt row in the step panel draws its attempt id,
and each element of a fan-out's output its run item id, in mono with the copy button the run id
has. The step's code is the panel's heading and is not drawn again on either.

**A run is named by when it started.** A run has no name of its own and its id is a handle for
machines, so what heads one is its pipeline's code and the instant it began, spelled the house way
and with the id on hover. `Run` is the word that stands in over the pipeline's name until there is
a run loaded to name -- the palette's shelf while the read is in flight -- and it is followed by
the pipeline and the instant the moment there is one. A queued run has not started, so every one
of those readings takes `started_at ?? created_at` and none of them can draw a blank.

**How a run was started is one fact, said once.** `startedAs` in `lib/runs` is the one phrase,
on the runs listing's Trigger cell, the pipeline page's Recent runs, the run's header and its
Trigger section. A person or a token is named by the label alone -- `agent (token mcp-trial)`
already says it was a token, so `api token` is not drawn beside it -- and the header reads it after
`by`. A schedule, a backfill or a source is its kind with the code it names, `schedule nightly`.
A run started by a step of another names that run by its short id, `a step of run 32ee6409`, and a
rerun the run it repeated, `rerun of 32ee6409 by admin`; on the run's Trigger section that run is
the link. What the server recorded, uuid and all, is on hover. The Trigger column is prose: it
truncates in its share rather than widening the table.

**The runs grouped by pipeline.** The Runs screen's View switch shows one row per pipeline that
ran in a window (`?group=pipeline&window=24h`; 1h, 24h or 7d): the title by the quartet, the newest
run's state, a dot and a count per state it has runs in -- a state with none is not drawn -- the
most recent runs as dots, oldest left and newest right, each a link to its run with its state and
when on hover, when it last ran, and the median duration of the settled ones. A row opens the flat
list of that pipeline over the same window. The strip is cut from the left where the cell is
narrower than it, so the newest run is the one always shown.

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
written, and what a step actually runs is never a click away. What the step is doing -- what it is
waiting on, what it saved to, what went wrong -- is on the box's tooltip, and the panel says the same
things as facts rather than as a second sentence.

**A live wait's fraction is a foot line, never a number.** A step whose attempt reports how far
its wait has come draws that as a line in the hue of the state it is in: 2px along the node's
bottom edge, inside its border and taking no height, and 3px directly under the attempt row's
waiting message. It is a `progressbar` with `aria-valuenow`, the node's tooltip gives the percentage, and
no figure is drawn beside it, because the message already says how far. It is drawn only while the
attempt is waiting or running: a settled attempt still carries the last fraction it reported, and
`progressOf` in `lib/run-detail` is the one reading that drops it. No progress draws nothing.

## The terminal drawer

A run's screen stacks: the canvas above, and a console across the foot of the content area at
the height somebody dragged it to. The right panel is beside both and is untouched by either --
what is beside a run is a different question from what is under it. It is opened from a glyph in
the run screen's own strip, from a row in the palette, and by pressing `T`, which is a bare
letter because every chord this app has is already spoken for.

**The terminal is the run's one log.** The run screen draws no second list of the same lines. A
run that failed opens on the terminal, for that visit and without writing the preference; any
other run opens it as the reader last left it. Choosing a box on the graph narrows the terminal to
that step, the way its own step filter does, and a running run tails live in it. The failure panel
says what failed in its own words -- the step, the block, the catalogued code, the sentence -- and
the terminal carries every line, the failing one among them, so the two repeat each other in that
one line and nowhere else.

**The drawer docks in the page's scroller.** It stands at the foot of the body, held to the bottom
of the one scroller while the body above it scrolls, so the panels above it and the drawer share
one right edge.

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
as a document key or a CLI verb. It never narrates a button that is on the screen: what New does
is what New says. **The second one is a sentence, not a clause hung off a dash**: "No blocks
installed. Plugins contribute them." is the shape, and every empty state on every screen is that
shape or the bare fact alone -- one of them punctuated its own way for long enough that the
catalogue could show it beside the others. **A way in that is off screen is stated wherever it is
off screen**, so a listing whose rows are declared by a document says so even where a button
beside it declares one too. A listing carries an `API` chip linking `/docs#/<tag>`, the fragment Swagger UI
writes on its own tag headings, so the requests behind a screen are one click away. Every screen
states its own two facts in the status line through `lib/screen-status`, the address nothing
answers for included.

**A heading names the category, in one noun where a noun exists, and never lists the values of
a column beneath it.** The Status column is already telling every row which state it is in,
and a heading that enumerates two of them breaks the moment a third qualifies. **Nor does a
heading name the reader's situation**: that states an obligation the screen cannot know
anybody has. Where a noun for the category already exists anywhere in this product -- in the
wire, in the engine, in the CLI -- that is the noun, because a screen may not coin a second
name for something already named. **A chart is titled with what it plots**, and the window,
the bucketing and the axis stay in the line beneath it.

## The palette's anatomy

sokkel-ui's `CommandPalette`: a search row, shelved rows, and a foot with the mark, what Enter
does and the chord that opens it. **The screen's own shelf leads** -- `shelve` in `lib/palette`
puts every shelf whose rows claim `screen` first, and the heading is free to name what it is
scoped to, such as the run being read. **A row is a mark and a title, nothing else.** What an
action says about itself (`hint`) is a word the row is found by and is never drawn: beside every
title it is a column of glosses saying what the titles already say. A row with no icon gets the
neutral glyph rather than a gap.

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

## Every word has a code, and they all live in one file

**`src/lib/labels.ts` is the only place a user-visible string may be written.** Every heading,
button, field label, placeholder, empty state, tooltip, `aria-label`, column header, confirmation,
palette row and settings row is a label in that catalogue, and a component reads one rather than
holding one. It is the same shape the server has had all along: `dirigent_common.messages` keeps
one `Catalogue` per area, mints a dotted code per message, and offers a walk over all of them at
once, so that a refusal can be rendered in another language by code. This is that in TypeScript's
idiom -- a section per area, the path through `LABELS` as the code, a duplicate name refused by
the compiler, `everyLabel()` as the walk.

**A sentence the wire drives is a template, not a function.** Everywhere else a value in a
sentence makes that label a function, because a caller in this bundle passes the value and the
compiler checks the call. A refusal's values arrive as a map off the wire, so there is no call to
check and nothing for a signature to buy: the `refused` section names its holes instead --
`No run {run_id}.`{ .label } -- and the name has to be one the server's own template writes. That is the
one place in the catalogue where a value is not a parameter, and
`scripts/check_refusal_labels.py` holds both halves to each other so a renamed param fails the
gate rather than sending the renderer quietly back to English.

**The code says what the string is for, never what it says.** `connections.check_row` is still
right when its words become `Ask again`; `connections.check_now_button_text` is wrong the moment
anybody edits it. Concretely: name a label after the outcome it is on the way to, not after the
mechanism that gets there or the phrase currently in it. Codes are lowercase words joined by
underscores, nested one level further where a single concept has more than one surface form.

**A concept holds its surface forms together.** A run that ended with failed items is a chip on a
row, a number on a tile and a clause in a sentence, and those were three phrases in three files
until they became `state.run.completed_with_errors.{chip,tile,sentence}`. Putting them under one
code is what makes a fourth spelling visible while it is being written. The same goes for the
health words, the worker words and the run states: one concept, one code, its forms beneath it.

**A noun is one entry, and the case belongs to the surface rather than to the word.** A field's
label, a column header, a card's fact and a section heading are Sentence case; a definition-list
term, a chip and a fragment inside a sentence are lower case. Where the product draws one noun in
more than one of those, the entry holds each form it actually draws, under the surface it is drawn
on: `label` for the singular a control or a column wears, `heading` for the plural over a section
or a table, `term` for the lower-case singular a definition list reads, `count` for the sentence a
listing's foot counts in. A form nothing draws is not written down, and nothing derives one
form from another -- capitalising in code compiles English's capitalisation rule into the app,
which is the one thing this catalogue exists to keep out. `Started` beside `started`, and `Blocks`
beside a per-screen `blocks`, are that rule not yet applied.

**A counted surface holds both numbers, so `count` is a `{one, many}` pair.** A foot counts rows
and a row may be one of them, so the entry spells the singular as well: `count: {one: 'schedule',
many: 'schedules'}`, and `counted` picks. A word that also stands alone in a sentence is written
again under `term`, because that is a surface of its own -- the two hold the same string in
English and need not in a language that declines a counted noun, which is exactly the difference
a shared entry would hide.

**A verb is one entry in `action`, and the states of its own control sit under it.** The word on
the button, the word while the request is in flight and the word once it has landed are one
concept, so they are `verb`, `busy` and `done` beneath one code -- never a `Creating` minted
again on each screen that writes something. A pair of verbs that toggles one thing, Pause and
Resume or Enable and Disable, is two entries side by side there rather than a pair per screen.

**A counted sentence is a `{one, many}` pair, never a ternary and never two sibling codes.**
`` `${count} field${count === 1 ? '' : 's'}` `` is English's plural rule compiled into the
catalogue, and a language with three plural forms, or with none, cannot write itself into that
string; two codes a stem apart, `stores_one` beside `stores_many`, are the same pair with the
concept pulled apart. So both forms are spelled whole under one code and the component picks
between them -- the shape five entries already had while five more were still branching inside
the string.

**A read in flight says `Reading`, and says nothing else.** Naming what is being read -- the
artifacts, the report, the corpus -- adds no fact the pane it is drawn in has not already given,
and "from the server" adds none at all, because every read in this app is from the server. One
code on every card, button and pane whose answer has not landed.

**A string with a value in it is a function taking named parameters**, so a language that puts
the value somewhere else can. Nothing here reads a locale and nothing chooses a table; a second
language is `const nb: typeof LABELS = {...}`, which the compiler checks for a missing code, a
stray code, and a sentence that takes different parameters. That is the whole reason the
catalogue exists, and the reason it is not worth arguing with.

**What is not a label**: a wire value (`completed_with_errors`, `cron`), an element id, a
`data-testid`, a class name, a URL or a path, a media type, an icon name, the key cap in a
`<Kbd>`, and the `keywords` a palette action is filtered on but never draws. One word a person
reads is spelled outside the catalogue and it is named there: a state a plugin contributed, which
this bundle was built before and cannot hold a table of, is spelled from the wire by
`statusLabel`.

`scripts/check_ui_labels.py` holds the rule, in `make static` and `make ui-lint`: it refuses a
literal between JSX tags, at an attribute or property a person reads, in a toast, or anywhere at
all if it is sentence-shaped, and it refuses a label in the catalogue that no source reads.
It cannot see a bare lower-case word returned from a lib function, because nothing reading the
text can tell one from a wire value -- review and `scripts/ui_copy.py` cover that.

**Documentation that quotes a label backticks it and marks it `{ .label }`.** A released note
once named a screen's heading in running prose, the heading was renamed, and the note went on
saying a word the product had stopped saying with nothing to catch it. Nothing could: `docs/`
holds 652 distinct backticked phrases and a handful of them are labels, so a check that guessed
would be mostly false alarm. The author says which instead:

```markdown
The account dialog's `Reset password`{ .label } button ends every session of the account.
```

`scripts/check_docs_labels.py`, in `make static` and `make ui-lint`, then refuses a marked phrase
the catalogue no longer holds, exactly as written, naming the page and the line. It is
`attr_list`, so the phrase renders as the inline code it already was; a marked page needs nothing
else, and a marker inside a fenced block is teaching the syntax rather than quoting the product.
**A phrase quoted with no marker on it is not checked**, which is the price of not guessing --
so a label named in prose is named this way or the sentence is written not to need it. What the
*server* says is not a label and takes no marker: a refusal's own wording is held to Python by
`scripts/check_refusal_labels.py` and by `dirigent-cli/tests/test_shared_words.py`.

## Interface copy is plain, and most of it is absent

A label, a hint, a description in the interface is plain product English: "Timezone",
"Follow logs", "Change your password." The house voice -- the wry sentence, the deliberate
turn of phrase -- belongs in this documentation and in commit messages, never in the words a
person reads while working. If a native speaker would not put it on a settings row, it does
not go on a settings row.

**The context says most of it; a sentence survives only by adding a fact.** Concretely:

- A screen carries no subtitle. "Pipelines" needs no line saying it lists the pipelines.
- The status line's note exists only when it is stateful -- the editor's shape and warnings,
  the run's settled tone, the workers' health. A static note restating the screen is noise.
- A section heading over a headed table carries no gloss; the headers name the columns.
- A dialog's description earns its lines by teaching semantics the controls cannot show
  (what sealing a secret means), never by describing the dialog.

**A copy defect is a pattern, not an instance.** Fixing one gibberish line means sweeping
every screen for the same pattern in the same change -- the ui-review skill says the same.

**The door greets, and its eyebrow is the one line of text in the app set in the accent.** It is
`SignIn`'s eyebrow, uppercase in `--primary-ink`: the door is the one screen with
nothing on it to act on but the button beneath it, so the colour that means action is free to
name the product there. The login screen alone carries that eyebrow, a heading, a one-line subtitle and
leading field icons, because it is the one screen a person meets before the
product's own facts are on it: there is no data to read, no title to take a heading from and no
shell around it, so the screen has to say where somebody has arrived and what to do next. No
other screen may copy any of it -- an eyebrow over a page title, a subtitle under a heading, a
placeholder repeating a label or the heading it sits under, or an icon inside a field is a defect
everywhere behind this door -- with one exception, the search glyph that leads every search box,
which says what kind of box it is rather than repeating a label. **A listing's search box says
`Search` and nothing more**, from sokkel-ui's `SearchField`: the heading over it already names what is being searched, and the noun
and what a match is made over stay on its accessible name, which is read without that heading
beside it. A box on a surface whose subject no heading states says what it matches over instead
-- a picker's `Search by name or code`{ .label }, the terminal's `Search lines`{ .label }, the palette's own row.

**The brand pane never carries a tagline.** What is on it is the mark, the word `dirigent`, and
the instance and the version the door answers for. A line saying what the product is for is
marketing on the one screen whose only question is who is asking, and the graph over the name
already says what is through the door.

## Design system

**Every recurring shape on a screen is one component, sokkel-ui's where the library has it and
otherwise one in `src/components/ds`, and a page does not hand-build what one of them covers.** A
lead cell, a chip, a dot, an icon-only button, a search box, a heading inside a screen, a list of
facts, a field, a notice, a dialog, a page heading and a link are each drawn one way, by the
component below, and a screen that typed the classes out again is a second answer to a question the
system has already answered. `/design` draws every component in every variant and state -- enabled,
shut with a reason, hovered, focused, empty, loading, long text truncating -- in both modes; it is
offered by the palette ("Design system") and not by the rail. A component that needs a new variant
gets it in `ds/`, or in sokkel-ui for one of the library's, and on that screen first, then on the
page that asked. **The gallery is named for what somebody is looking for, not for how the code files
it**: Text (Titles, Headings, Links), Marks (Labels, Status dots, Icons), Controls (Buttons, Search,
Form fields, Switches), Containers (Notices, Dialogs, Lists of facts), with an index beside them
that follows the scroll and a plain sentence under a heading only where it adds a fact. A component
keeps its own name in the code. A specimen stands on the section's card with no frame of its own,
and a `TopBar` specimen draws no palette button (`palette={false}`): the page's own top bar holds
the one palette.

| Component | When |
| --- | --- |
| `ItemHeading` (sokkel-ui) | Any addressable thing headed by its name and code, given as `{...itemOf(thing)}` so the name is the one `headingOf` finds. `stacked` puts the code under the name, for a listing's lead cell; `inline` beside it, where a row has one line; `size="dialog"` inside a dialog's title, where it is a `span`, with `lead={LABELS.action.edit}` while the dialog edits the thing; `as="span"` wherever the heading is not in the page's outline. A long name gives way before the inline code, which stays on screen. The name, else the code; the code always on screen in mono and never twice; a glyph before it, chips after it, an optional one-line description |
| `Chip` (sokkel-ui) | A word on a chip: `neutral`, `mono` for a key, `absent` dashed for an absence, `good`, `critical`, `warning`, `info`; `icon` before the word. `onSelect` makes it a button named by `selectLabel`, saying what pressing does ("Filter by finance"); `onRemove` adds an X with its own focus ring, named by `words={chipWords(...)}` from a function of the chip's words ("Stop filtering by finance"). Neither press reaches the row or card around the chip, so a pressable row needs no guard of its own. It replaces the hand-typed chip and the pill `Badge` for a word. `KindChip` stays, on the same 20px and the same radius |
| `StatusChip` (sokkel-ui) | A state as a chip, with the dot the `StatusProvider` gives every chip: the state's color on a wash of it, the word from `STATUSES`. A live state's dot pulses -- queued, running, waiting, sending -- and a paused or settled one is still; the pulse stops for somebody who asked for less motion. `label` where a screen names the state in its own terms, such as a count in flight |
| `Dot` (sokkel-ui) | Every state drawn as a dot, given as `{...dotOf(...)}` from one map: a tone (`good`, `critical`, `warning`, `info`, `quiet`, `unknown`, the last hollow) or a run status, 8px. A dot alone is the answer -- a green dot says connected -- and its word is its name and its tooltip. The word is drawn beside it only when it is news: failed, unknown. `tip` adds a sentence to the tooltip, and `focusable` puts the dot in the tab order where nothing around it is a control. `StatusChip` takes a `label` where a screen names the state in its own terms |
| `IconButton` (sokkel-ui) | Any button that is an icon and nothing else, the glyph its child, which is why every icon button has a tooltip. Its type requires `label`; the tooltip is the label or a longer `tooltip`, with `reason` under it when it is shut. Sizes `icon-xs`, `icon-sm` and `icon`. Shut with `reason`, never with `disabled`, so it stays reachable; `destructive` tints critical under the pointer |
| `SearchField` (sokkel-ui) | Every box that narrows a screen, `placeholder={SEARCH_PLACEHOLDER}` and `words={SEARCH_WORDS}`. A leading search glyph, a clear button once there is text, Escape to clear, and the `/` key cap: `/` moves the caret into the screen's one box that binds it, never while another field, the editor or a dialog has focus. A second box on the screen passes `shortcut={false}` |
| `GroupLabel` (sokkel-ui) | The one faint uppercase label over a run of rows inside a screen, `as="h3"` where it heads them in the outline. A part of a page with a title of its own is a `Section` |
| `DescriptionList` (sokkel-ui) | Facts about one thing, given as `items`. The default `side` layout is a term column of `termWidth` beside a value column, a panel's and a dialog's; `code` sets a value in mono, and a term that is a document key is an `InlineCode`. `layout="row"` is small facts wrapping on one line, a heading's strip. A missing value is a quiet dash |
| `Field`, `SwitchField` (sokkel-ui) | Every field: a prose label or a mono key, `required` with `requiredMark="word"` and `words={FIELD_WORDS}`, a hint, help and the `fallback` an empty box submits under the control in one ink, an error on the issue mark at the control's end. `SwitchField` is a boolean setting as a row, the whole row its label, `explain` on a help mark and `reason` under the label while it is shut |
| `Callout`, `Surface` (sokkel-ui) | `Callout` is a sentence that must not be missed, `critical`, `warning` or `neutral`, with the tone's mark. `Surface` `tone="well"` is a group that belongs together, on the panel ground, `pad` for fields or text; `tone="inset"` is reference material -- JSON, a code block, a log that follows its tail -- on the page's ground. A refusal off the wire is still `Refusal` |
| `DialogShell` (sokkel-ui) | Every dialog, `words={DIALOG_WORDS}`: a width from `sm`, `md`, `lg`, `xl`, a title and description, a body that scrolls under a fixed head and foot, and a footer of `Cancel` and one confirm that stays reachable while shut, or of `actions` on a dialog that reads one thing. `closeOnOutsidePress={false}` for a form somebody is typing in |
| `ConfirmDialog` (sokkel-ui) | Before every verb that takes something away -- revoke, deactivate, delete, rotate. The title is the question and names the thing, its code in mono and nowhere else: `Delete ops-hook-2?`. There is no body, because the verb says what is lost. It holds one line only when that line changes the answer: what stops the verb, which shuts the confirm with the reason on its `title`, or what the verb takes beyond the thing named. `Question` draws the question around the code, `detail` is the one line, and a refusal off the wire is one short `RefusalLine`, with no box and no second naming of the thing. A verb that cannot go without one value holds that one field: a password reset's new password. No such verb is immediate. Its confirm wears sokkel-ui's destructive tint, the critical ink on its wash, as every verb that takes something away does |
| `SecretReveal` (sokkel-ui) | A secret the server answers with once: the value whole in mono on its own field, wrapped rather than cut, a copy button that says it copied and resets, and the line in the warning ink saying it is shown once. `secretWords` names the copy button for the secret and says that line |
| `CopyButton` (sokkel-ui) | The ghost icon button beside a string somebody pastes elsewhere -- a secret, a URL, a command line: it puts the string on the clipboard, says it copied, and resets. `copyWords` gives it its name and the copied word |
| `PageHeader`, `SplitButton` (sokkel-ui) | A screen's heading, sokkel-ui's `PageHeader` drawn into the shell's head slot by dirigent's. Its verbs are `items`, which fold from the last into "More actions" in the room the title leaves, and one `primary` after them, filled, that never folds, a `SplitButton` when it carries `more`, its chevron named by the item's `moreLabel`. The row is words only; More carries the marks. A title that is the code is cut short with the whole of it on hover. A verb's `label` is its name and `face` the shorter word on the button: `New` named "New pipeline". `lead` stands before the verbs and never folds -- the API chip; a `count` beside the title; a `code` under it in mono for a detail screen, with `meta` a line of small facts under that; a `trail` for a detail screen. No subtitle. A screen whose strip is not a heading -- the editor's -- puts the same items in sokkel-ui's `Toolbar` |
| `TextLink` (sokkel-ui) | Every link that is text, through the app's `LinkProvider`. `inline` in prose, in ink and underlined, `data` for a number or a reference in a table (`code` for mono), `aside` in the muted ink beside a section heading; `external` with `words={LINK_WORDS}` adds its mark and a new tab; `onPress` is a link that opens something in place |
| `InlineCode` (sokkel-ui) | Every code, key, block and kind in mono, `bare` at `size="xs"`. One line, truncated with an ellipsis, the whole value on `title`; `tone="muted"` beside a title, `tone="neutral"` where the code is the value, and `size="sm"` where it heads a row |
| `Section` (sokkel-ui) | Every section of a page: a title bar with the label and a count or fact beside it, `actions` at its right end, a rule, a body on the card, a hairline edge and no shadow. `tone="graph"` puts the canvas's dot grid on the body, `critical` is the failure with its top rule and warning mark. `flush` where the body's rows lay out their own padding, `headingId` where something links to it. A titled listing is a `flush` `Section` with its count as `meta`, around a `DataTable` with `framed={false}` |
| `DataTable` (sokkel-ui) | Every listing, spread with `LISTING` (`variant="list"`, `resizable={false}`, `stackBelow` and `minWidth`): grid tracks per column with the title `width: 'content'`, a cell's control pressed on its own without opening the row, `onOpen` and `opened` for what a row opens, `rowTone="muted"` for a row no longer live, `rowHeight="auto"` where a cell is two lines, `detail`, `hasDetail` and `expandLabel` for what stands under an opened row, `hasMore` and `onLoadMore` for the cursor, the count as `foot` from `rowsRead` or, where the listing has a bar, through `words={countWords(...)}`, `search` and `toolbar` for the box and the filters that narrow it, and `empty` for the one line a listing with no rows says |
| `FilterChip`, `ListingBar` (sokkel-ui) | A filter in a listing's bar: `facet`, `options` (a `row` where the value has a drawing of its own), `multiple` for a set, the chosen held through `selected` and `onSelectedChange` -- `oneChosen` for a single value -- and `words={filterWords(any)}`. `ListingBar` is the bar `DataTable` draws, for a search over several tables or over a list that is not one |
| `ConsequenceList`, `DiffView` (sokkel-ui) | `ConsequenceList` is what an action changes or takes with it, a row per kind with its `count` and a `detail` line, under a heading from the catalogue: `neutral` for what changes, `critical` for what goes; it draws nothing without rows. `DiffView` is two versions of a text as one list of lines, `size="sm"` in a dialog, inside a `WindowedPane` with `WindowedPaneButton` at its default `icon-xs` in its `actions` slot; it folds unchanged runs in the pane and draws every line (`context={Infinity}`) in the window, with no `title` there so no header row is drawn, says `DIFF_WORDS`, and a caller that would hand it two equal texts draws nothing instead |
| `MiniGraph` (sokkel-ui-graph) | A pipeline's shape at the scale of a row, from `miniGraphSteps`, with `scale="natural"`, `align="start"` and `reduce`: one pitch shrunk only to fit the lead cell, sources dashed, fan-outs stacked, implied edges left out, a failed step filled, the step's key and block on hover, `label` the pipeline's title |

**A mark comes from `lib/icons` and nowhere else.** `ICONS` maps every concept the interface
draws a mark for -- create, edit, delete, run, rerun, pause, resume, cancel, refresh, recheck,
clear a filter, search, copy, external, settings, fit the view, open in a window, upload, a
template, the sidebar, and the nouns: pipeline, run history, step, block, connection, schema, trigger, schedule, source, user,
token, worker -- to one lucide icon, named for what it means rather than where it was first drawn,
and no two concepts to the same one: fitting the canvas is
`Scan` and opening a pane in a window is `Maximize2`. A page or a component that needs a mark
with no concept adds the concept there. A kind's mark is still `lib/glyphs`.

**Nothing is fully round but a status dot and an avatar.** A chip, a control, a card, a dialog
and a switch take the radius ladder's rungs, and no class names a radius of its own.

**`scripts/check_ui_system.py` holds the system**, in `make static` and `make ui-lint`. Under
`src/pages` and `src/components`, the generated primitives and `components/ds` excepted, it
refuses a hand-typed word chip (one class string holding `rounded-sm`, `border`, `px-1.5` and
`text-xs`), a `Button` sized `icon*` rather than an `IconButton`, an import from `lucide-react`
(which it refuses in `components/ds` as well), and an arbitrary `rounded-[...]`. What predates
the check is recorded in `scripts/ui_system_offenders.txt`, one line per rule and file with its
count. It is a ratchet: a file may hold exactly what is recorded, one more is refused as new and
one fewer as stale, so the change that moves a screen onto the system shrinks the record with
`--write` in the same commit.

## An ellipsis means the action asks for more before it acts

**A control's word ends in `…` when pressing it does not yet do what the word says, because it needs
something more from the person first**: a file, a choice from a picker, a form. `From a file…`,
`From a template…`, `Add step after…`, `Run…`, `Send a test…`, `Reset password…`, `Change…`,
`Set up slack…`. The same action is written the same way on a button, a menu item and a palette row.
What it opens is titled without the mark, because by then the question is on screen.

These do not wear it, and each is a decision:

- **A create following the `New` rule below.** `New`, `New token` and a palette's `New alert rule` or
  `Create an account` say what they open, and every create is one.
- **A verb raising `ConfirmDialog`, and an `Apply` opening its plan.** Those ask for a yes and nothing
  else, so `Delete`, `Deactivate`, `Revoke`, a source's `New token` and `Apply` stay as they are. A confirm's
  own verb is the act. `Reset password…` wears it because that question also needs a new password.
- **A word whose outcome is the opening.** `Edit` is true the moment it is pressed: you are editing.
  `Add a window` adds the section. `Change…` wears it because nothing has changed yet.
- **A place.** `Settings` and `Keyboard shortcuts` are somewhere to go, not an action.
- **A control with no word.** The canvas's `+` is an icon, and its tooltip names it.
- **An action that acts.** `Use as template` copies and goes there, and `Validate` answers at once.

## A create button says `New`

On a screen whose heading names the noun, the primary create button says `New` alone: the screen
supplies the object. The full name stays on the control's `aria-label`, on the palette action,
which is offered from every screen and so needs the noun, and on whatever the button opens. A
screen offering more than one create -- Triggers -- keeps the noun on each button, because `New`
alone would not say which. The create is the strip's primary either way, and wears the fill. A create that belongs to one row is on that row and names its noun:
`New token`{ .label }, on the account it is for.


