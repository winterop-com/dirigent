/**
 * Every word this interface says to a person, each under a code.
 *
 * THE SAME SHAPE AS THE SERVER'S. `dirigent_common.messages` holds one `Catalogue` per area,
 * mints a dotted code per message, refuses a duplicate name, and keeps `Catalogue.all` so one
 * test can walk every string in the process at once. This is that, in TypeScript's idiom: a
 * section per area, the path through `LABELS` as the code, a duplicate name refused by the
 * compiler rather than at import, and `everyLabel` as the walk. A refusal the server sends
 * arrives with its own code already on it and is rendered through `lib/refusal`; nothing here
 * duplicates one.
 *
 * THE CODE SAYS WHAT THE STRING IS FOR, NEVER WHAT IT SAYS. `connections.check_row` stays
 * right when the words become `Ask again`; `connections.check_now_button_text` would not. A
 * code that has to change when the wording changes is the wrong code.
 *
 * A CONCEPT HOLDS ITS SURFACE FORMS TOGETHER. A run that ended with failed items is drawn as a
 * chip, counted on a tile, and named in a sentence, and those three were three different
 * phrases written in three files. They sit under one code here -- `state.run.completed_with_errors`
 * -- so a fourth spelling is visible while it is being written rather than found by grep.
 *
 * A SENTENCE WITH A VALUE IN IT IS A FUNCTION. Named parameters, so a translation writes the
 * value wherever its own grammar puts it rather than wherever English does.
 *
 * TRANSLATION IS A SECOND TABLE, NOT A REWRITE. `const nb: typeof LABELS = {...}` is checked
 * by the compiler: a missing code, a stray code, or a sentence that takes different parameters
 * is a type error. Nothing here chooses a table, and nothing here reads a locale -- that is
 * machinery this product does not have yet, and the shape is what keeps it cheap to add.
 *
 * WHAT DOES NOT LIVE HERE. A wire value (`completed_with_errors`, `cron`), an element id, a
 * `data-testid`, a class name, a URL or a path, and the keywords the palette filters on but
 * never draws. `scripts/check_ui_labels.py` states the boundary and holds it.
 */

/** A sentence a value is written into, taking its parameters by name. */
export type Sentence = (...params: never[]) => string

/** One label: the text, or the shape of the sentence it is drawn as. */
export type Label = string | Sentence

/** One area's labels, or one concept's surface forms. */
export type Catalogue = { readonly [name: string]: Label | Catalogue }

/**
 * The verbs this product puts on a control.
 *
 * THEY ARE HERE SO THERE IS ONE OF EACH. A dialog that dismisses without writing says the same
 * word on every screen, and a screen that wants a different word has to add one to this list in
 * front of everybody.
 */
const action = {
    /** Leave a dialog that would have written something, writing nothing. */
    cancel: 'Cancel',
    /** Leave a dialog that has already done what it was opened for. */
    close: 'Close',
    /** Leave a dialog whose work is finished and whose answer has been read. */
    done: 'Done',
    /** Write the new thing the dialog was opened to make. */
    create: 'Create',
    /** Write the edits made to a thing that already exists. */
    save: 'Save',
    /** Write the document to the instance. */
    apply: 'Apply',
    /** Check the document against the instance without writing it. */
    validate: 'Validate',
    /** Start a run. */
    run: 'Run',
    /** Start another run of what this one ran. */
    rerun: 'Re-run',
    /** Stop what is running. */
    cancel_run: 'Cancel',
    /** Open the thing for editing. */
    edit: 'Edit',
    /** Take the thing away for good. */
    delete: 'Delete',
    /** Take away what a token can do, keeping the record of it. */
    revoke: 'Revoke',
    /** Put a thing back to a known state. */
    reset: 'Reset',
    /** Replace one value with another. */
    change: 'Change',
    /** Make the thing this screen lists one more of. */
    new: 'New',
    /** Ask an external system whether the credential still works. */
    check: 'Check now',
    /** Ask again for what is already on screen. */
    recheck: 'Recheck',
    /** Mint a value the person should not have to invent. */
    generate: 'Generate',
    /** Send one message through a channel to see whether it arrives. */
    send_test: 'Send a test',
    /** Try the delivery that failed once more, now. */
    retry_now: 'Retry now',
    /** End this session. */
    sign_out: 'Sign out',
} as const

/**
 * The nouns this product labels things with.
 *
 * ONE NOUN, ONE ENTRY. The same word is a field's label, a column's header and a card's term,
 * and it is one word in all three places or the product has two names for one thing. A noun
 * that only one screen ever draws stays on that screen's section instead.
 */
const word = {
    /** The addressable key, unique and constrained. */
    code: 'Code',
    /** The optional human title, which carries no identity at all. */
    name: 'Name',
    /** The long-form, markdown-capable text. */
    description: 'Description',
    /** What family a thing belongs to. */
    kind: 'Kind',
    /** Whichever state machine's word applies. */
    status: 'Status',
    /** The state a rule or a trigger is in, as distinct from how its last delivery went. */
    state: 'State',
    /** Whether the external system answered. */
    health: 'Health',
    /** A definition. */
    pipeline: 'Pipeline',
    /** One execution of a pipeline. */
    run: 'Run',
    /** One node of a pipeline. */
    step: 'Step',
    /** What a step is, out of the catalog. */
    block: 'Block',
    /** A named credential. */
    connection: 'Connection',
    /** A shape a payload is checked against. */
    schema: 'Schema',
    /** A shipped document. */
    example: 'Example',
    /** What fires a pipeline without a person. */
    trigger: 'Trigger',
    /** A clock that fires a pipeline. */
    schedule: 'Schedule',
    /** An inbound endpoint that fires a pipeline. */
    webhook: 'Webhook',
    /** A step that waits for an external condition. */
    watch: 'Watch',
    /** An alert rule. */
    rule: 'Rule',
    /** One queued alert delivery. */
    notification: 'Notification',
    /** A node that claims work. */
    worker: 'Worker',
    /** A person's record. */
    account: 'Account',
    /** A person's code, which is what they sign in as. */
    username: 'Username',
    /** What an account is reachable at. */
    email: 'Email',
    /** What an account may do. */
    role: 'Role',
    /** What an account signs in with. */
    password: 'Password',
    /** The leading characters a token is recognised by. */
    prefix: 'Prefix',
    /** Which plugin contributed the thing. */
    plugin: 'Plugin',
    /** Where a pack keeps its examples. */
    shelf: 'Shelf',
    /** The free-form words a listing narrows by. */
    tags: 'Tags',
    /** What a document declares it needs of an instance. */
    requires: 'Requires',
    /** The block's own settings. */
    config: 'Config',
    /** The values a run was started with. */
    parameters: 'Parameters',
    /** What a step wrote. */
    output: 'Output',
    /** The files a run wrote. */
    artifacts: 'Artifacts',
    /** What a run rendered when it settled. */
    report: 'Report',
    /** The short form of what a run amounts to. */
    summary: 'Summary',
    /** The lines a run wrote. */
    log: 'Log',
    /** The document as it was written. */
    source: 'Source',
    /** The document a run was pinned to. */
    definition: 'Definition',
    /** Which apply a version came from. */
    version: 'Version',
    /** Where a worker runs. */
    host: 'Host',
    /** How many steps a worker claims at once. */
    concurrency: 'Concurrency',
    /** Which zone a schedule is read in. */
    timezone: 'Timezone',
    /** Which clock a schedule keeps. */
    clock: 'Clock',
    /** Where a webhook is posted to. */
    endpoint: 'Endpoint',
    /** Whether a webhook's payload is signed. */
    signature: 'Signature',
    /** How much a webhook may be posted. */
    rate_limit: 'Rate limit',
    /** What a rule listens for. */
    event: 'Event',
    /** How wide a rule's reach is. */
    scope: 'Scope',
    /** How much a pipeline matters. */
    importance: 'Importance',
    /** Where a run sits in the queue. */
    priority: 'Priority',
    /** The line an alert leads with. */
    subject: 'Subject',
    /** What an alert says. */
    body: 'Body',
    /** How long a rule waits before it fires again. */
    throttle: 'Throttle',
    /** Which channel an alert is delivered through. */
    delivers_through: 'Delivers through',
    /** How long something took. */
    duration: 'Duration',
    /** The span a run reads over. */
    window: 'Window',
    /** The beginning of a span. */
    start: 'Start',
    /** The end of a span. */
    end: 'End',
    /** Where a watch has read up to. */
    cursor: 'Cursor',
    /** The values a trigger always passes. */
    pinned_parameters: 'Pinned parameters',
    /** How a webhook's payload becomes parameters. */
    payload_mapping: 'Payload mapping',
    /** How this instance is deployed. */
    environment: 'Environment',
    /** Where this instance keeps its records. */
    database: 'Database',
    /** Where this instance keeps its artifacts. */
    storage: 'Storage',
    /** When the thing was made. */
    created: 'Created',
    /** When the thing was last asked. */
    checked: 'Checked',
    /** When the thing last happened. */
    last_seen: 'Last seen',
    /** When something is next due. */
    next: 'Next',
    /** Nothing at all, where a field would otherwise be blank. */
    none: 'none',
    /** Never, where a field holds no moment. */
    never: 'never',
} as const

/**
 * The state machines, as words.
 *
 * THE WIRE'S VALUE IS THE KEY AND NEVER THE LABEL. `completed_with_errors` is what the server
 * says; what a person reads is drawn from here, so a state this product has one name for does
 * not acquire a second one on the next screen.
 *
 * A STATE A PLUGIN CONTRIBUTED HAS NO ENTRY, and cannot: this bundle is built before the plugin
 * is installed. `statusLabel` spells one from the wire instead, which is the one place in the
 * app where a word a person reads was not written down here.
 */
const state = {
    /** Where a run is. `RunStatus` in dirigent_client.enums. */
    run: {
        /** Read, not yet claimed by a worker. */
        queued: {
            chip: 'queued',
            tile: 'Queued',
            sentence: 'Waiting for a worker.',
        },
        /** Claimed, with at least one step in flight. */
        running: {
            chip: 'running',
            tile: 'Running',
            sentence: 'Being worked on now.',
        },
        /** Every step succeeded. */
        succeeded: {
            chip: 'succeeded',
            tile: 'Succeeded',
        },
        /** Settled, with at least one step failed under a rule that let the rest carry on. */
        completed_with_errors: {
            chip: 'completed with errors',
            tile: 'With errors',
            sentence: 'finished with errors',
        },
        /** Settled with a step that stopped it. */
        failed: {
            chip: 'failed',
            tile: 'Failed',
        },
        /** Stopped because somebody asked. */
        cancelled: {
            chip: 'cancelled',
        },
    },
    /** Where one try of one step is. `AttemptStatus` in dirigent_client.enums. */
    attempt: {
        pending: 'pending',
        queued: 'queued',
        running: 'running',
        waiting: 'waiting',
        succeeded: 'succeeded',
        failed: 'failed',
        skipped: 'skipped',
        cancelled: 'cancelled',
    },
    /** Whether a credential answered the last time anything asked it. */
    health: {
        /** Nothing has ever asked. */
        unchecked: 'never checked',
        /** The kind publishes no check, so asking proves nothing. */
        unverified: 'not verified',
        /** It answered. */
        healthy: 'healthy',
        /** It did not answer, as a row's word and as a sentence. */
        failed: {
            word: 'failed',
            sentence: 'did not answer',
        },
    },
    /**
     * What a worker's row says is wrong with it, keyed by the concern `lib/workers` reads out
     * of its heartbeat. The concern's own name is a discriminator and is never drawn.
     */
    worker: {
        silent: 'has gone quiet',
        mismatched: 'is running a different catalog from this server',
        draining: 'is draining',
        stopped: 'has stopped',
        starting: 'is still starting',
    },
    /** How the instance as a whole is doing, as the door's own button says it. */
    server: {
        asking: 'asking…',
        healthy: 'healthy',
        degraded: 'degraded',
        unhealthy: 'unhealthy',
        offline: 'offline',
    },
    /** Whether a thing fires at all. */
    armed: {
        /** A schedule that will not fire until somebody resumes it. */
        paused: 'paused',
        /** A webhook or a rule that answers nothing. */
        disabled: 'disabled',
        /** A rule that is listening. */
        active: 'active',
        /** A rule that is switched off. */
        off: 'off',
        /** An account that can no longer sign in. */
        deactivated: 'deactivated',
        /** A token that no longer opens anything. */
        revoked: 'revoked',
    },
    /** Where the run's event stream is, along the foot of the run screen. */
    stream: {
        connecting: 'connecting',
        live: 'live',
        reconnecting: 'reconnecting',
    },
} as const

/**
 * How a measured value is written.
 *
 * THESE ARE COPY, NOT ARITHMETIC. The numbers are computed in `lib/format`; what is here is the
 * shape each one is written in, because a language that does not put the unit after the number
 * cannot be served by a format string this product hid inside a function.
 */
const measure = {
    /** Under a second. */
    milliseconds: (value: string) => `${value}ms`,
    /** Under a minute. */
    seconds: (value: string) => `${value}s`,
    /** Minutes, with the seconds that do not make another minute. */
    minutes: (minutes: string, seconds: string) => `${minutes}m ${seconds}s`,
    /** Hours, with the minutes that do not make another hour. */
    hours: (hours: string, minutes: string) => `${hours}h ${minutes}m`,
    /** A count of bytes, spelled out. */
    bytes: (value: string) => `${value} B`,
    /** Close enough to now that a span would be noise. */
    just_now: 'just now',
    /** A span, when it is behind us. */
    ago: (span: string) => `${span} ago`,
    /** A span, when it is ahead of us. */
    ahead: (span: string) => `in ${span}`,
    /** The short spans a relative time is written in. */
    span: {
        minutes: (value: string) => `${value}m`,
        hours: (value: string) => `${value}h`,
        days: (value: string) => `${value}d`,
    },
    /** The zone a timestamp is read in, when it is not the reader's own. */
    utc: 'UTC',
    /** A zone's offset, where a zone has none of its own. */
    utc_offset: 'UTC+0',
    /** From one moment to another. */
    range: (from: string, to: string) => `${from} to ${to}`,
} as const

/**
 * What each screen is called, and the one line the navigation says about it.
 *
 * ONE NAME PER SCREEN. The rail's entry, the palette's row and the page's own heading are the
 * same words, because they are the same screen. A screen whose heading is not its name says so
 * here, in front of the others, rather than quietly in its own file.
 */
const screen = {
    /** The front door: what this instance is doing right now. */
    dashboard: {
        name: 'Dashboard',
        hint: 'How this instance is doing',
    },
    /** The definitions. */
    pipelines: {
        name: 'Pipelines',
        hint: 'Definitions and their versions',
    },
    /** Every execution. */
    runs: {
        name: 'Runs',
        hint: 'Every execution, newest first',
    },
    /** What fires a pipeline without a person. */
    triggers: {
        name: 'Triggers',
        hint: 'Clocks and inbound endpoints',
    },
    /** The credentials. */
    connections: {
        name: 'Connections',
        hint: 'Named credentials and their health',
    },
    /** What the installed plugins contribute. */
    blocks: {
        name: 'Blocks',
        hint: 'What the plugins contribute',
    },
    /** The documents the plugins ship. */
    examples: {
        name: 'Examples',
        hint: 'The documents the plugins ship, and the starters',
    },
    /** The shapes a payload is checked against. */
    schemas: {
        name: 'Schemas',
        hint: 'Shapes a payload is checked against',
    },
    /** The section the admin screens sit under. */
    admin: 'Admin',
    /** The instance, for whoever runs it. */
    overview: {
        name: 'Overview',
        hint: 'This instance, at a glance',
    },
    /** Accounts and the tokens they mint. The heading is not the name. */
    users: {
        name: 'Users',
        hint: 'Accounts and automation tokens',
        heading: 'Users and tokens',
    },
    /** The nodes that claim work. */
    workers: {
        name: 'Workers',
        hint: 'The nodes claiming work',
    },
    /** The rules and the delivery queue. */
    alerting: {
        name: 'Alerting',
        hint: 'Rules and the delivery queue',
    },
    /** An address nothing answers for. */
    nowhere: 'Nothing at this address',
} as const

/**
 * The frame every screen is drawn inside.
 *
 * The rail and the drawer, the topbar and the corner that names the instance, the right panel
 * and the sheet it becomes on a phone, the bar along the foot, the shortcuts dialog and the
 * theme controls -- plus the chrome a listing, a table and a page state wear on every screen,
 * which belongs to the frame rather than to whichever screen is inside it.
 */
const shell = {
    /** The product's own name: the mark's label, and what the corner says before any read lands. */
    wordmark: 'dirigent',

    /** What the rail's own controls do, which the collapsed rail says as tooltips. */
    collapse_nav: 'Collapse the navigation',
    expand_nav: 'Expand the navigation',
    resize_nav: 'Resize the navigation',

    /** The drawer the rail becomes below the breakpoint, and the region it stands in. */
    open_nav: 'Open navigation',
    close_nav: 'Close navigation',
    nav_region: 'Navigation',

    /** The trail across the top of a screen that is one thing rather than a listing. */
    breadcrumb: 'Breadcrumb',

    open_palette: 'Open the command palette',
    /** The chord on the palette's button: this platform's modifier, and the letter. */
    palette_chord: (modifier: string) => `${modifier}K`,
    toggle_panel: 'Show or hide the side panel',
    open_settings: 'Open settings',
    shortcuts: 'Keyboard shortcuts',

    /** The corner: which instance this is, what it is running, and how it is doing. */
    instance: {
        label: 'Instance',
        /** The name, and the environment where the environment is worth saying. */
        line: (name: string, environment: string) => `${name} · ${environment}`,
        /** What offline amounts to, beside the word itself. */
        offline: 'the server did not answer',
        /** Leads the time since the last ask. */
        checked: 'checked',
        environment: 'environment',
        version: 'version',
        /** A fact this instance did not state. */
        unknown: 'not said',
    },

    /** The bar's own cell, and the row at the foot of the drawer that opens the same dialog. */
    settings: 'Settings',

    resize_panel: 'Resize the side panel',
    /** The tab strip's heading where the screen in front of the panel has filled no tab. */
    panel: 'Panel',
    panel_empty: 'Nothing selected.',
    close_panel: 'Close the panel',

    /** The menu a screen's verbs fold into where the strip cannot hold them all. */
    more_actions: 'More actions',

    /** The corner toggle, which names the mode a click would put the app in. */
    switch_to_light: 'Switch to light',
    switch_to_dark: 'Switch to dark',
    /** The mode axis: the Theme pane's control, and the palette's appearance rows. */
    mode: {
        light: 'Light',
        dark: 'Dark',
        system: 'System',
    },
    /** The colour palettes this build carries, as the Theme pane's swatch cards name them. */
    colours: {
        dirigent: 'Dirigent',
        paper: 'Paper',
        contrast: 'Contrast',
    },

    /** What each chord does, on the shortcuts dialog's rows. The palette's row says `open_palette`. */
    chord: {
        rail: 'Collapse or expand the navigation',
        terminal: "Show or hide a run's terminal",
        shortcuts: 'Open this list',
        dismiss: 'Close a dialog, a menu, or the palette',
        choose: 'Open the row that has focus',
    },

    /** The card a screen shows while its read is still in flight. */
    reading: 'Reading from the server',

    /** The box that narrows what is on the screen. It names nothing: the heading above it does. */
    search: 'Search',
    /** A filter menu's trigger: what it filters, and what it is set to. */
    filter: (name: string, chosen: string) => `${name}: ${chosen}`,
    /** What a picker says when nothing in its list answers to what was typed. */
    no_match: 'No match.',
    /** The tag filter, and the two things its trigger says. */
    tag_filter: {
        label: 'Filter by tag',
        any: 'Any tag',
        chosen: 'Tag',
    },
    /** One tag chip, which narrows the listing to itself. */
    filter_by_tag: (tag: string) => `Filter by ${tag}`,
    /** The same tag, once it is narrowing. */
    stop_filtering_by_tag: (tag: string) => `Stop filtering by ${tag}`,
    /** The tags a row had no room for, spelled out behind the `+N`. */
    folded_tags: (count: string, tags: string) => `${count} more tags: ${tags}`,

    /** The button at the foot of a table that reads the next page, and the same button in flight. */
    load_more: (count: string) => `Load ${count} more`,
    loading_more: 'Reading',
    /** What a listing's foot states. It says there is more rather than passing a count off as a total. */
    rows_read: (count: string, noun: string) => `${count} ${noun}`,
    rows_read_more: (count: string, noun: string) => `${count} ${noun}, more to load`,

    /** The refresh control: the verb, and the cadence the screen then keeps on its own. */
    refresh: 'Refresh',
    cadence: 'How often this refreshes on its own',
    cadence_off: 'Off',
    cadence_seconds: (value: string) => `${value}s`,
    cadence_minutes: (value: string) => `${value}m`,

    /** The button that puts a pane in a window as large as the screen allows. */
    open_in_window: (name: string) => `Open ${name} in a window`,
    /** What the pane inside that window is called. */
    in_window: (name: string) => `${name}, in a window`,
    /** The way out of a screen and into the requests behind it. */
    api_docs: (section: string) => `The ${section} section of this instance's API documentation`,

    /** What the graph canvas offers in its corner. */
    zoom_in: 'Zoom in',
    zoom_out: 'Zoom out',
    fit_view: 'Fit view',
} as const

/**
 * What the command palette says for itself.
 *
 * The rows are not here: every one of them is a screen's name, a verb, or an appearance setting,
 * and each is said once wherever it is also drawn on a control. What is here is the palette's
 * own chrome and the headings it shelves those rows under.
 */
const palette = {
    title: 'Command palette',
    description: 'Every place this app can go, and everything it can do from here',
    placeholder: 'Go to a screen, or run something',
    empty: 'Nothing here answers to that',

    /** What the two keys along the foot do. */
    foot: {
        choose: 'choose',
        run: 'run it',
    },

    /** The headings the rows are shelved under, in the order the palette lays them out. */
    shelf: {
        go: 'Go to',
        admin: 'Admin',
        view: 'View',
        /** What the screen in front of somebody can do, which only that screen registers. */
        run: 'Run',
        /** What a listing screen offers over its own rows: a filter, a refresh, the verb it owns. */
        list: 'This listing',
        /** What the front door offers over the instance it describes, which is not a listing. */
        dashboard: 'This screen',
        appearance: 'Appearance',
        session: 'Session',
    },
} as const

/**
 * What this bundle says when there is no refusal off the wire to say it for us.
 *
 * A refusal the server sent arrives as a problem document with its own code on it and is drawn
 * in the words the server wrote; nothing here duplicates one. These are the refusals this app
 * makes itself: a request that never reached a server, an answer that was not a problem
 * document, a control shut by the account's role, a password the form refuses without asking,
 * and an address nothing answers for.
 */
const refusal = {
    /** The heading over a request that never reached a server. */
    no_answer: 'No answer',
    /** The sentence under it. */
    unreachable: 'This server did not answer. It may be starting, or the connection was lost.',
    /** The heading over a refusal whose body was not a problem document, which is its status. */
    http_status: (status: string) => `HTTP ${status}`,
    /** The sentence under that one. */
    no_problem_document: (status: string) => `The server answered ${status} with no problem document.`,
    /** What anything that went wrong amounts to, where nothing else was said. */
    no_reply: 'The server did not answer.',

    /** What a control behind a role gate says on hover, and the roles it says it to. */
    shut: (role: string) => `Not available to ${role}.`,
    role: {
        operator: 'an operator',
        viewer: 'a viewer',
    },

    /** An admin screen reached by typing its address. No request was made, so no status phrase. */
    admin_only: {
        title: 'Forbidden',
        detail: "This screen is an admin's. Operators may define, run and observe pipelines; managing accounts, tokens and connections is an admin's.",
    },

    /** What the password form refuses on its own, before there is anything to ask. */
    password: {
        title: 'Not accepted',
        current_missing: 'Type the password this account signs in with now.',
        too_short: (characters: string) => `A password must be at least ${characters} characters.`,
        unchanged: 'The new password is the one already in use.',
        /** The change went out and nothing came back. */
        no_answer: 'The server did not answer. The password has not been changed.',
    },

    /** An address this app does not answer, said where it was opened rather than redirected away. */
    nowhere: {
        detail: 'This app does not answer for the address in the browser bar.',
        /** The one fact the status bar states while that screen is open. */
        note: 'no screen at this address',
    },
} as const

/**
 * What the door says.
 *
 * THE ONE SCREEN ALLOWED AN EYEBROW, A HEADING, A SUBTITLE AND PLACEHOLDERS, which is why this
 * section holds shapes no other section may: docs/ui-conventions.md says so, and says no other
 * screen may copy any of it.
 */
const login = {
    /** The wordmark on the brand pane, which is the product's name and is lower case. */
    wordmark: 'dirigent',
    /** The term over the host somebody typed to get here. */
    instance: 'instance',
    /** The term over the version that host answered with. */
    version: 'version',
    /** The line above the heading. */
    eyebrow: 'Welcome to dirigent',
    /** The heading, and the word on the button that submits it. */
    sign_in: 'Sign in',
    subtitle: 'Enter your credentials to continue.',
    username_placeholder: 'Your username',
    password_placeholder: 'Your password',
    /** The button's tooltip while it will not take a second submit. */
    working: 'Signing in',
    /** What the reveal toggle says it will do next, which is the opposite of what it has done. */
    show_password: 'Show password',
    hide_password: 'Hide password',
    /** What the dragged seam between the two panes is, for a reader who reaches it by key. */
    seam: 'Resize the brand pane',
} as const

/**
 * What the front door and the admin overview say.
 *
 * ONE SECTION FOR TWO SCREENS. The dashboard and the admin overview ask the same questions of
 * the same listings and draw the answers with the same components, so a word one of them uses
 * is a word the other reaches for; the few places where they say the same fact differently are
 * two codes here, next to each other, rather than two files apart.
 */
const dashboard = {
    /** The palette row that reads the front door's listings again. */
    refresh: 'Refresh the dashboard',
    /** The palette row that reads the admin overview's listings again. */
    refresh_overview: 'Refresh the overview',
    /** A card whose read has not landed. */
    reading: 'Reading',
    /** What the chart and the health panel say in place of their own line while reading. */
    reading_from_server: 'Reading from the server',
    /** A count and the noun it counts, which every tile's sentence is assembled out of. */
    counted: (count: string, noun: string) => `${count} ${noun}`,
    /** Some out of a whole, which is what a tile reads when its value counts two numbers. */
    of: (some: string, all: string) => `${some} of ${all}`,

    /** The numbers each screen opens with, and the one line under each of them. */
    tile: {
        /** Under the front door's count of the window. */
        runs_window: 'Last 24 hours.',
        /** The admin overview's name for the same window, which carries no full stop. */
        day: 'Last 24 hours',
        /** Nothing at all was started in the window. */
        day_empty: 'Nothing has run in the last day.',
        /** Something was started in the window and none of it has settled. */
        day_none_settled: 'Nothing has finished.',
        /** What a run nobody has claimed is counted as in the "right now" sentence. */
        waiting: 'waiting to be claimed',
        /** Nothing has registered with this instance. */
        workers_empty: 'No worker has registered with this instance.',
        /** Every worker answered. */
        workers_well: 'Every worker is answering.',
        /** This instance holds no credentials at all. */
        connections_empty: 'This instance holds no connections.',
        /** One credential refused: which one, what its state is called, and what it said. */
        connection_failed: (code: string, said: string, detail: string) => `${code} ${said}${detail}`,
        /** What the external system said, where it said anything. */
        said: (detail: string) => `: ${detail}`,
        unverified: (count: string) => `${count} could not be verified.`,
        never_checked: (count: string, verb: string) => `${count} ${verb} never been checked.`,
        /** The verb that agrees with the count of credentials nothing has asked yet. */
        has: 'has',
        have: 'have',
        /** Every credential answered. */
        connections_well: 'Every connection answered when it was last checked.',
        /** How much of this instance fires without a person. */
        schedules: 'Schedules',
        schedules_empty: 'Nothing on this instance fires on its own.',
        schedules_across: (scheduled: string, pipelines: string) =>
            `Across ${scheduled} of ${pipelines} pipelines.`,
    },

    /** The bar chart of the last day, and the reading of it for somebody not seeing it. */
    chart: {
        title: 'Runs over time',
        hint: 'Every run started in the last 24 hours, by the hour it started in.',
        /** One bar's title, where nothing was started in that hour. */
        hour_empty: (hour: string) => `${hour} — nothing ran`,
        /** One bar's title: the hour, how much started in it, and how that came out. */
        hour: (hour: string, started: string, settled: string) => `${hour} — ${started} started, ${settled}`,
        /** Runs were started in the hour and none of them has settled. */
        none_settled: 'none finished',
        /** The chart's accessible name, where the window held nothing. */
        summary_empty: 'No run was started in the last 24 hours.',
        /** The chart's accessible name: how much was started, then how it came out. */
        summary: (started: string, outcomes: string) =>
            `${started} runs started in the last 24 hours, by the hour: ${outcomes}.`,
    },

    /** The panel beside the chart: the workers and the connections as one list. */
    health: {
        hint: 'The workers claiming work, and every connection.',
        /** A worker with nothing to report: what it is, and how much it can take. */
        worker: (count: string, slots: string) => `worker · ${count} ${slots}`,
        slot: 'slot',
        slots: 'slots',
        /** The noun the connections half of the foot is counted in. */
        connections: 'connections',
        /** The workers half of the foot, which is drawn only where it is not perfect. */
        no_worker: 'no worker has registered',
        workers_healthy: (well: string, total: string) => `${well} of ${total} workers healthy`,
        /** Both halves well, on an instance that holds no credentials. */
        every_worker_well: 'Every worker is healthy, and this instance holds no connections.',
        /** Both halves well. */
        all_well: 'Every worker and every connection is healthy.',
    },

    /** What is in flight, which is the front door's first feed. */
    right_now: 'Right now',
    nothing_live: 'Nothing is running and nothing is waiting.',
    /** The runs that want somebody, on both screens. */
    needs_a_look: 'Needs a look',
    nothing_to_look_at: 'Nothing has failed or finished with errors.',
    /** The firings still ahead. */
    next_fires: 'Next fires',
    no_fire_due: 'No schedule is due to fire.',
    /** The admin overview's workers table with nothing in it. */
    no_workers: 'No workers. Start one with dg worker; nothing is claimed until one registers.',

    /** What each feed's footer counts its rows in. */
    noun: {
        runs: 'runs',
        firings: 'firings',
    },

    /** The column headers of the three feeds. */
    column: {
        /** When a live run started. */
        since: 'Since',
        /** The step a run died in. */
        failed_at: 'Failed at',
        /** What that step said. */
        error: 'Error',
        /** When the run was last doing anything. */
        when: 'When',
        /** When a schedule goes off next. */
        fires: 'Fires',
    },
} as const

/** The pipelines listing, its rows, and the picker that starts one from a shipped starter. */
const pipelines = {
    /** The split button that opens the editor on a document nothing has applied. */
    new: 'New pipeline',
    /** Behind its chevron: a document read off disk. */
    from_file: 'From file…',
    /** Behind its chevron, and the title of the picker it opens: a copy of a shipped starter. */
    from_starter: 'From a starter',
    /** The chevron itself. */
    more_ways: 'More ways to start a pipeline',
    /** What the palette offers on this screen, where a rail button says it shorter. */
    palette: {
        from_starter: 'New pipeline from a starter',
        from_file: 'New pipeline from a file',
        reload: 'Read the pipelines listing again',
    },
    /** The box over the table, which narrows the rows already read. */
    search: 'Search pipelines by code, name or tag',
    /** What the foot of the table counts. */
    noun: 'pipelines',
    /** How many rows the search left, out of how many were read. */
    shown_of_loaded: (shown: string, loaded: string) => `${shown} of ${loaded}`,
    /** The column headers no shared noun covers. */
    column: {
        triggers: 'Triggers',
        last_run: 'Last run',
    },
    /** The mark beside the title of a pipeline that matters more than every other one. */
    critical: {
        chip: 'critical',
        explained: 'critical: an alert rule may fire for this pipeline and for no lesser one',
    },
    /** The mark beside the title of a pipeline the instance no longer runs. */
    deactivated: {
        chip: 'deactivated',
        explained: 'deactivated: its schedules are paused and it cannot be run',
    },
    /** What fires a pipeline on its own, which is what the glyphs in the column are titled with. */
    trigger_summary: {
        /** Each kind, counted: the plural is the singular with an s, except where it is here. */
        schedule: 'schedule',
        webhook: 'webhook',
        watch: 'watch',
        watches: 'watches',
        /** The last count, joined to the ones before it. */
        and: (counts: string, last: string) => `${counts} and ${last}`,
        none: 'nothing fires this on its own',
    },
    /** How the newest run of a pipeline reads in the listing. */
    last_run: {
        /** Runs are in flight, so the cell counts them rather than naming the last one. */
        running: (count: string) => `${count} running`,
        /** A run that was read before a worker put a moment on it. */
        not_started: 'not started',
        /** Nothing has ever run. */
        never: 'never run',
        /** Which step the run stopped at. */
        failed_at: (step: string) => `at ${step}`,
    },
    /** What the table says when it has nothing in it, which a chosen tag is a reason for. */
    empty: {
        /** Rows were read, and the search box left none of them on screen. */
        filtered: 'No loaded pipeline matches that.',
        /** The listing was narrowed to one tag nothing wears. */
        tagged: (tag: string) => `No pipeline is tagged ${tag}.`,
        /** Narrowed to several, which nothing wears all of. */
        all_tags: (tags: string) => `No pipeline wears all of ${tags}.`,
        /** This instance holds none. */
        none: 'No pipelines.',
    },
    /** The picker over the installed starters. */
    starters: {
        /** Under the title, saying what choosing one does. */
        description: 'Copy a shipped document into the editor, under a code of your own',
        placeholder: 'Search the starters',
        /** What was typed matches no starter. */
        empty: 'No starter answers to that',
        /** The corpus has not arrived yet. */
        reading: 'Reading the corpus',
        /** Nothing installed here ships one. */
        none: 'No starters installed — plugins contribute them.',
    },
} as const

/**
 * What the pipeline editor says.
 *
 * ONE SCREEN, SEVEN SURFACES. The strip above the canvas, the canvas and its menus, the panel's
 * four tabs, and the two dialogs that reach the instance. A few words are read by more than one
 * of them and sit at the head of the section rather than in whichever tab happened to draw one
 * first.
 */
const editor = {
    /** What a pane says when the pipeline has no version behind it to read. */
    no_document: 'This pipeline has no version, so there is no document to read.',
    /** Where a step's block would be named, on a step that names none. */
    no_block: 'no block',
    /** What a step with no prerequisites waits for. */
    no_prerequisites: 'nothing; this step is a root',
    /** A code naming a connection this instance does not hold. */
    not_configured: 'not configured',
    /** The name the same pane takes when it is opened in a window of its own. */
    in_window: (pane: string) => `${pane}, in a window`,
    /** The name the skeleton document gives itself. */
    new_document_name: 'My pipeline',

    /** Which version the instance holds, wherever that is drawn. */
    version: {
        /** The mono chip, where the instance holds no version of this pipeline at all. */
        none: 'no version',
        short: (version: string) => `v${version}`,
        unapplied: 'No version of this pipeline has been applied.',
        counted: (version: string) =>
            `Version ${version} of this pipeline, counting the applies that changed it.`,
    },

    /** The strip above the canvas, and what this screen contributes to the command palette. */
    topbar: {
        /** What the breadcrumb and the palette's shelf call a document nothing has applied yet. */
        new_pipeline: 'new pipeline',
        /** The palette shelf this screen's rows sit on. */
        shelf: (group: string, pipeline: string) => `${group} — ${pipeline}`,
        /** The chip counting what differs from the version the instance holds. */
        unapplied_edits: (count: number) => `${String(count)} unapplied edit${count === 1 ? '' : 's'}`,
        /** The status bar's count of what this instance has not got. */
        unmet_here: (count: number) => `${String(count)} unmet here`,
        /** Why Run is shut on a document the instance holds no version of. */
        not_applied: 'Apply this document before running it.',
        /** Why everything that writes is shut while the source pane does not parse. */
        unparsed: 'The source pane holds text that is not a document.',
        /** What the strip says below the breakpoint, where the verbs that write are not drawn. */
        read_only: 'Read only on a small screen',
        /** The palette row that opens the run dialog. The dialog itself is titled with the verb. */
        run_pipeline: 'Run pipeline',
        /** The palette row that gives the whole arrangement back to elk. */
        relayout: 'Re-layout the graph',
        /** A run the instance accepted without starting one, and said nothing more about. */
        nothing_started: (status: string) => `nothing started: ${status}`,
    },

    /** The canvas: the boxes, the menus every add-step gesture opens, and the empty state. */
    canvas: {
        no_steps: 'No steps.',
        /** The canvas with no document behind it to draw. */
        nothing_to_draw: 'No version to draw.',
        /** The other way into a document, which is copying a shipped one. */
        from_starter: 'From a starter',
        /** The menu's own heading, the control that opens it, and the palette row that fires it. */
        add_step: 'Add step',
        /** The same menu, opened out of a step, which the new one will wait for. */
        add_step_after: (step: string) => `Add step after ${step}`,
        /** What the menu's box narrows, in the words of what it searches. */
        search_blocks: 'Search blocks by id, summary or kind',
        no_block_matches: 'No block matches that.',
        /** A box's own menu: one more step after this one, and this one taken away. */
        add_after: 'Add step after',
        delete_step: 'Delete step',
        /** A step whose block this instance does not publish, as the chip on its box. */
        not_installed: 'not installed',
        not_installed_title: (block: string) =>
            `${block} is not installed on this instance, so this step will fail`,
        /** A step that differs from the version the instance holds. */
        edited: 'edited',
        /** A fan-out over a list a run resolves, so there is no count to draw. */
        fan_out_each: 'each',
        fan_out_each_title: 'for_each: runs once per item of the list it is given',
        fan_out_count: (count: string) => `×${count}`,
        fan_out_count_title: (count: string) => `for_each: runs once per item, ${count} of them`,
        /** Why an edge was refused, in the words of the steps that refuse it. */
        cycle_refused: (dependent: string, prerequisite: string, loop: string) =>
            `${dependent} cannot wait for ${prerequisite}: that closes a loop, ${loop}`,
    },

    /** The panel's step tab: what the chosen step runs, and the config it takes. */
    step: {
        /** The tab itself, which carries the chosen step's key. */
        tab: (step: string) => `Step · ${step}`,
        /** The panel with no step chosen. */
        none_chosen: 'No step chosen.',
        reading_schema: "Reading this block's schema.",
        name_placeholder: 'What to call this step on screen',
        /** Under the name box: a name is a display string and the key is what is referenced. */
        name_note: (step: string) => `Display only. Every reference to this step is by its key, ${step}.`,
        /** Above the list of what one field's own schema refuses. */
        refused_at_apply: 'This step will be refused at apply.',
        add_prerequisite: 'Add a prerequisite',
        stop_waiting: (step: string) => `Stop waiting for ${step}`,
    },

    /**
     * The five groups the engine's half of a step is read in, and the one line each says shut.
     *
     * A shut group's line carries the values the document sets and the defaults it leaves alone,
     * so every fragment here is part of a sentence about what would actually run.
     */
    step_groups: {
        waits_for: 'Waits for',
        fan_out: 'Fan-out',
        timing: 'Timing',
        retry: 'Retry',
        /** When a step becomes ready, over the steps it waits for. Not an alert rule. */
        rule: 'Rule',
        /** A fan-out, or a retry policy, that the document does not ask for. */
        off: 'off',
        no_timeout: 'no timeout',
        poll_own_cadence: 'poll its own cadence',
        no_deadline: 'no deadline',
        on_timeout: (choice: string) => `on_timeout ${choice}`,
        attempts: (count: string) => `${count} attempts`,
        backoff: (delay: string) => `${delay} backoff`,
        /** What each delay is multiplied by, and the delay it stops growing at. */
        growth: (multiplier: string, ceiling: string) => `×${multiplier} up to ${ceiling}`,
        jitter: (spread: string) => `jitter ${spread}`,
        continues_on_failure: 'continues on failure',
    },

    /**
     * What each member of the engine's half of a step does, as the hint under its control.
     *
     * These mirror `StepDefinition` and `RetryPolicy` in `dirigent_core.engine.definition`, so a
     * control says here what an apply would enforce there.
     */
    step_keys: {
        rule: 'When this step becomes ready, over the steps it waits for.',
        for_each:
            "A reference to a list, or a literal list: one run item per element. A reference may read params, run, and an upstream fan-out's grid as ${steps.<name>.items}, which maps this step over that step's items.",
        items: 'Whether one failed item stops the batch, or the rest carry on.',
        timeout: 'How long one attempt may take.',
        poll: "How often a sensor checks. Defaults to the sensor's own cadence.",
        deadline: 'How long the step may wait before the timeout applies.',
        on_timeout: 'What an expired deadline does to the step.',
        continue_on_failure: 'Dependents still run when this step fails, and the run completes with errors.',
        max_attempts: 'Total attempts, including the first.',
        backoff: 'The delay after the first failure.',
        max_backoff: 'The longest delay between attempts.',
        multiplier: 'What each delay is multiplied by.',
        jitter: 'How much of the delay is spread randomly.',
    },

    /** The panel's pipeline tab: what the document is, what it reaches, and what it has done. */
    pipeline_pane: {
        no_description: 'This pipeline carries no description.',
        no_parameters: 'This pipeline takes no parameters.',
        /** A parameter's bounds, where the schema states them as a length. */
        length_range: (shortest: string, longest: string) => `${shortest}..${longest} chars`,
        /** A parameter's fallback, where the schema declares one. */
        default_of: (value: string) => `default ${value}`,
        /** The section over the connections the document names. */
        connections: 'Connections',
        no_connections: 'This pipeline names no connections.',
        /** A connection this instance holds, whose last check said it answered. */
        answering: 'answering',
        not_answering: 'not answering',
        /** A named connection the listing has not landed for, so nothing is claimed about it. */
        health_unread: 'health unread',
        requires_nothing: 'This document requires nothing in particular of an instance.',
        block_chip: (block: string) => `block ${block}`,
        connection_chip: (connection: string) => `connection ${connection}`,
        pipeline_chip: (pipeline: string) => `pipeline ${pipeline}`,
        missing_chip_title: (thing: string) =>
            `${thing} is not installed on this instance, so applying and running this document will fail`,
        /** The section over what fires this pipeline without a person. */
        triggers: 'Triggers',
        no_triggers:
            'Nothing fires this pipeline on its own. A document declares them under its triggers key.',
        /** The three kinds of trigger, as each row of the list leads with them. */
        schedule: 'schedule',
        webhook: 'webhook',
        watch: 'watch',
        /** Between a watch and the step it watches. */
        watch_on: 'on',
        /** A schedule declaring none of the keys that would say when it fires. */
        no_clock: 'no clock',
        recent_runs: 'Recent runs',
        no_runs: 'No runs.',
        versions: 'Versions',
        no_versions: 'No versions.',
        /** A version whose apply recorded nobody, such as one a worker applied. */
        not_recorded: 'not recorded',
    },

    /** The panel's report tab: whether a run writes a report, and what it writes it from. */
    report: {
        /** The segmented control over the document's three answers. */
        choice: 'What a run of this pipeline reports',
        none: 'No report',
        builtin: 'Built-in template',
        own: 'Own template',
        writes_none: 'A run of this pipeline writes no report document.',
        builtin_says:
            "The built-in document is the run's facts, a table of its steps, and its error. It is not part of this document.",
        own_says: "This template is rendered against the run's facts when the run settles.",
        /** The way out to the documentation of what a template is rendered against. */
        reference: 'What a template may read',
        placeholder: '# {{ pipeline.code }} {{ run.status }}',
    },

    /** The panel's source tab: the document as the text it is written in everywhere else. */
    source: {
        /** What a screen reader and a test call the pane. */
        pane: 'The document',
        loading_editor: 'Loading the editor.',
        /** Under the parse error, saying what the rest of the screen is showing meanwhile. */
        stale: 'The other tabs are showing the last document that parsed.',
        /** Why the text in the pane is not a document, where the parser itself says nothing. */
        not_yaml: 'that is not YAML',
        empty: 'the document is empty',
        not_a_mapping: 'a document is a mapping of keys, not a single value',
    },

    /** The row under a config box holding a code, saying what that code names and where. */
    reference_row: {
        /** A schema code no instance and no document answers. */
        not_stored: 'not stored',
        /** A schema the document carries under its own top-level section. */
        carried: 'carried by this document',
        /** A code this instance's own listing answered. */
        instance: 'instance',
        open_schema: 'Open in Schemas',
        open_connection: 'Open in Connections',
    },

    /** The dialog that shows what applying would do, before anything is written. */
    apply: {
        title: 'Apply document',
        /** The same dialog with no button, so its title says which question was asked. */
        validate_title: 'Validate document',
        /** Said only by Validate: it would be untrue of what the apply button does. */
        nothing_written: 'Nothing was written.',
        checking: 'Checking the document.',
        /** Why the button is shut while the dry run is still out. */
        unchecked: 'The document has not been checked yet.',
        unacceptable: 'This document is not one the instance would accept.',
    },

    /** What the server said an apply would do, as the dialog and the status bar read it. */
    plan: {
        refuse: (pipeline: string) => `Apply will refuse ${pipeline}`,
        unchanged: (pipeline: string) => `Apply writes nothing — ${pipeline} is already at this document`,
        create: (pipeline: string) => `Apply creates ${pipeline} at version 1`,
        update: (version: string, pipeline: string) => `Apply writes version ${version} of ${pipeline}`,
        steps_added: (steps: string) => `steps added: ${steps}`,
        steps_removed: (steps: string) => `steps removed: ${steps}`,
        steps_changed: (steps: string) => `steps changed: ${steps}`,
        params_changed: 'the parameter schema changed',
        triggers_changed: 'the triggers changed',
        settings_changed: 'the name, description, or concurrency policy changed',
        /** A plan that would write a version, and change nothing a reader would scan for. */
        no_changes: 'No changes from the stored version.',
        /** What the instance refuses about the document, counted. */
        issues_refuse: (count: number) =>
            `${String(count)} issue${count === 1 ? '' : 's'} — apply will refuse`,
        /** What an apply that was carried out amounts to, in one line. */
        left_as_it_was: (pipeline: string) => `${pipeline} was left as it was`,
        at_version: (pipeline: string, version: string) => `${pipeline} is at version ${version}`,
        /** What an apply did to the triggers the document declares. */
        materialized: {
            schedules_created: 'schedules created',
            schedules_updated: 'schedules updated',
            schedules_removed: 'schedules removed',
            webhooks_created: 'webhooks created',
            webhooks_updated: 'webhooks updated',
            webhooks_removed: 'webhooks removed',
            watches_created: 'watches created',
            watches_updated: 'watches updated',
            watches_removed: 'watches removed',
        },
        /** One line of that: what happened, and the triggers it happened to. */
        change_line: (what: string, names: string) => `${what}: ${names}`,
    },

    /** The dialog that starts one ad hoc run of the version this instance holds. */
    run: {
        confirm: 'Run now',
        /** The link that offers the two boxes to a document that reads no window. */
        add_window: 'Add a window',
        /** The level the run's own log is filtered at. */
        log: 'log',
        log_level: 'log level',
        info_and_up: 'info and up',
        debug_too: 'debug too',
        /** The footnote: who the run is attributed to, and how it was started. */
        runs_as: (who: string) => `runs as ${who} · adhoc`,
        /** Who a run is attributed to when nobody is signed in. */
        this_session: 'this session',
    },

    /**
     * What this instance has not got of what the document names, one line per thing.
     *
     * A step is named with the block behind it: "not installed" without the step is a fact
     * nobody can act on, and the step is where the run will actually stop.
     */
    unmet: {
        step: (step: string, block: string) => `this run will fail at ${step}: ${block} is not installed`,
        block: (block: string) => `this document requires ${block}, which is not installed`,
        connection: (connection: string) => `the connection ${connection} is not configured on this instance`,
    },
} as const

/**
 * The form a JSON Schema is drawn as: what a field says about itself beside its label, the
 * table a map is edited in, and what a field says when the value in it is not one the schema
 * accepts.
 *
 * THE LABEL IS THE KEY IN THE DOCUMENT, so nothing here names a field: every sentence below
 * takes the key as a parameter and the document is what spelled it.
 */
const form = {
    /** A block or a pipeline whose schema publishes no fields at all. */
    no_configuration: 'This takes no configuration.',
    /** Beside the label of a field the schema requires. */
    required: 'required',
    /** Beside the label: what an empty box would submit. */
    default_is: (value: string) => `default ${value}`,
    /** Under a JSON box, where leaving it empty is what submits the default. */
    empty_submits_default: 'An empty box submits the default.',
    /** A choice with nothing chosen and no default behind it. */
    unset: 'unset',
    /** The link over the fields a form folds away; the count decides the plural. */
    more_fields: (count: number) => `${String(count)} more field${count === 1 ? '' : 's'}`,
    /** What an empty box shows where the schema declares no default: the shape it takes. */
    placeholder: {
        list: '["one", "two"]',
        map: '{"key": "value"}',
    },
    /**
     * The reader's words for the formats the shipped schemas publish, keyed by the schema's
     * own `format` with its hyphen written as an underscore, because a code has no hyphens. A
     * format with no words here is shown as the schema spelled it.
     */
    format: {
        size: 'bytes, or a size such as 1mb',
        duration: 'a duration such as 30s',
        storage_uri: 'a storage URI such as s3://bucket/key',
        date_time: 'a date and time such as 2026-03-01T12:00:00Z',
        time: 'a time of day such as 06:30',
        password: 'a secret',
    },
    /** The one line beside the label. */
    hint: {
        /** The values the schema offered as examples. */
        examples: (examples: string) => `e.g. ${examples}`,
        /** What the value cells of a map hold, where they hold anything but text. */
        pairs: (shapes: string) => `values are ${shapes}`,
    },
    /** Between the shapes one value may take, wherever a hint or a refusal lists several. */
    or: ' or ',
    /** The word a hint or a refusal names one shape by. */
    shape: {
        text: 'text',
        integer: 'a whole number',
        number: 'a number',
        switch: 'true or false',
        select: 'one of its options',
        pairs: 'a map',
        json: 'JSON',
    },
    /** Beside the label of a field whose value is a reference its own control cannot draw. */
    written_as_reference: {
        pairs: 'a reference, not a table',
        select: 'a reference, not a choice',
        switch: 'a reference, not a switch',
    },
    /** The two-column table a map of scalars is edited as. */
    pairs: {
        key: 'key',
        value: 'value',
        /** The column the remove button stands in, which is headed for a reader who hears it. */
        remove: 'remove',
        /** One cell, named for the field it is in and the row it is on. */
        key_cell: (field: string, row: string) => `${field} key ${row}`,
        value_cell: (field: string, row: string) => `${field} value ${row}`,
        /** The button that takes a row away, named by the key on it. */
        remove_key: (key: string, field: string) => `Remove ${key} from ${field}`,
        /** The same button on a row that has no key yet. */
        remove_row: (row: string, field: string) => `Remove row ${row} from ${field}`,
    },
    /** The pane a program or a JSON value is opened out into. */
    in_window: (field: string) => `${field}, in a window`,
    /** What a field says when its value is not one the schema accepts. */
    refusal: {
        required: (label: string) => `${label} is required`,
        not_null: (label: string) => `${label} may not be null`,
        /** A union, none of whose branches take the value. */
        shapes: (label: string, shapes: string) => `${label} is ${shapes}`,
        one_of: (label: string, options: string) => `${label} is one of ${options}`,
        boolean: (label: string) => `${label} is true or false`,
        text: (label: string) => `${label} is text`,
        number: (label: string) => `${label} is a number`,
        map: (label: string) => `${label} is a map, or a reference to one`,
        /** One entry of a map, named by its key. */
        entry: (label: string, key: string, shapes: string) => `${label}.${key} is ${shapes}`,
        /** The count decides the plural, so the number crosses rather than the text of it. */
        min_length: (label: string, count: number) =>
            `${label} is at least ${String(count)} character${count === 1 ? '' : 's'}`,
        max_length: (label: string, count: string) => `${label} is at most ${count} characters`,
        pattern: (label: string, pattern: string) => `${label} does not match ${pattern}`,
        whole_number: (label: string) => `${label} is a whole number`,
        minimum: (label: string, least: string) => `${label} is at least ${least}`,
        maximum: (label: string, most: string) => `${label} is at most ${most}`,
        greater_than: (label: string, least: string) => `${label} is greater than ${least}`,
        less_than: (label: string, most: string) => `${label} is less than ${most}`,
        /** Text in a JSON box that does not parse, where the engine said nothing itself. */
        not_json: 'that is not JSON',
        /** One cell of a map, holding something the map does not take. */
        map_values: (label: string, shapes: string) => `${label} values are ${shapes}`,
        duplicate_key: (label: string, key: string) => `${label} carries ${key} twice`,
    },
} as const

/**
 * The reference card beside a program: the idioms of the language it is written in, and the
 * rules this runtime adds to them.
 *
 * ONE TABLE PER GROUP, IN THE ORDER THE CARD DRAWS THEM. Each group holds its heading and one
 * line per row, named for what the row teaches rather than for the words the gloss uses, so the
 * row survives being reworded. The forms themselves -- `.a.b`, `argv: [cmd, arg]` -- are the
 * language's own syntax and stay in the component beside the glosses they belong to.
 */
const reference = {
    /** The line over the card, naming the language the program beside it is written in. */
    heading: (language: string) => `${language} reference`,
    /** The transform step's language. */
    jq: {
        title: 'jq',
        /** The link out to the language's own documentation. */
        manual: 'The jq manual',
        paths: {
            title: 'Paths',
            nested: 'a field of a field',
            ends: 'first and last of a list',
            each: 'each element in turn',
            optional: 'null instead of an error when it is not there',
            descend: 'every id, anywhere in the value',
        },
        shape: {
            title: 'Shape',
            object: 'an object from picked fields',
            list: 'a list from each element',
            added_field: 'an object with one more field',
            entries: 'an object as {key, value} pairs and back',
        },
        filter: {
            title: 'Filter and reduce',
            map: 'apply to each; keep the ones that match',
            aggregate: 'sum, count, extremes',
            group: 'lists by a key',
            unique: 'one per key; the smallest by key',
            reduce: 'a fold, with the state as .',
        },
        strings: {
            title: 'Strings and dates',
            case: 'case and trimming',
            split: 'a string as a list and back',
            convert: 'across the string boundary',
            encode: 'a list encoded for another program',
            now: 'the moment as ISO 8601',
            parse_date: 'a date string as seconds',
        },
        missing: {
            title: 'Missing values',
            alternative: 'the right side when the left is null or false',
            has_key: 'whether a key is there',
            drop_null: 'drop a null from a stream',
        },
        runtime: {
            title: 'In this runtime',
            bind_input: 'the input, bound for the rest of the program',
            environment: 'an empty object here: the worker keeps its environment',
            inputs: 'not available: the whole input is .',
        },
    },
    /** What a query step's statements are written in. */
    sql: {
        title: 'SQL',
        runtime: {
            title: 'In this runtime',
            bound_value: 'a value bound by name from params, never interpolated',
            statements: 'sql.query runs one; sql.execute runs several as one transaction',
            max_rows: 'the cap on what the output carries',
        },
    },
    /** What a command step runs. */
    shell: {
        title: 'shell',
        runtime: {
            title: 'In this runtime',
            argv: 'no shell: each argument as written',
            command: '/bin/sh -c, for a pipe or a redirect',
            environment: 'variables set here, and the worker variables let through',
            cwd: 'relative to the run’s work directory, never absolute',
        },
    },
    /** What a report is templated in. */
    jinja: {
        title: 'Jinja',
        /** The link out to what this runtime puts in front of a template. */
        manual: 'What a template may read',
        facts: {
            title: 'The facts',
            run: 'the run and what it was started with',
            pipeline: 'what ran',
            step: 'one step by name, its last output',
            steps: 'every step in order; the fan-out items',
            rendered: 'when this page was written, and the run’s address',
        },
        filters: {
            title: 'Filters',
            duration: '1s34ms',
            bytes: '1.2KB',
            iso: 'ISO 8601',
            builtin: 'Jinja’s own',
        },
        control: {
            title: 'Control',
            loop: 'a table row per step',
            conditional: 'a section only when a step ran',
            missing: 'renders as nothing, never an error',
        },
    },
} as const

/**
 * The runs listing and the one run screen: its graph, the panel's four tabs, and every sentence
 * `lib/run-detail` hands a node or a fact to draw.
 */
const runs = {
    // The listing.

    /** The button that folds in what arrived while the listing was being read. */
    fresh_one: '1 new run',
    fresh_many: (count: string) => `${count} new runs`,
    /** The palette's rows, which are the filters this screen offers as one gesture each. */
    filter_failed: 'Show only the runs that failed',
    filter_day: 'Show only the last 24 hours of runs',
    filter_clear: 'Clear every run filter',
    reload: 'Read the runs listing again',
    /** The accessible name of the box a pipeline code is typed into. */
    filter_pipeline: 'Filter runs by pipeline',
    /** What the status select is worth when no state is chosen. */
    any_status: 'Any status',
    /** One window the listing offers, named by the duration it covers. */
    window_option: (window: string) => `Last ${window}`,
    /** What the window select is worth when no window is chosen. */
    any_window: 'All of history',
    /** What the listing's footer counts, and what its More button asks for. */
    row_noun: 'runs',
    /** The column of when each run started. */
    column_started: 'Started',
    /** Which step a run died in, drawn in front of the refusal itself. */
    failed_at: (step: string) => `at ${step}`,
    empty_filtered: 'No run matches these filters.',
    empty: 'No runs. A pipeline is run from its own page, or by a schedule or a webhook.',
    /** The two priorities that are not the one every other run has. */
    priority_high: 'high priority',
    priority_low: 'low priority',
    /** Why a queued run has not started: no live worker carries the tags it asked for. */
    waiting_for_workers: (tags: string) => `waiting for a worker carrying ${tags}`,
    /** The last of those tags, joined to the ones before it. */
    waiting_tags: (rest: string, last: string) => `${rest} and ${last}`,
    /** Who started a run, where a step of another run did. */
    started_by_step: (run: string) => `a step of run ${run}`,

    // The run screen: its toolbar, its palette shelf and the graph.

    cancel_action: 'Cancel this run',
    rerun_action: 'Run this pipeline again',
    toggle_terminal: "Show or hide this run's terminal",
    /** What the palette says the terminal holds. */
    terminal_hint: 'Every line this run wrote, in the order it wrote them',
    copy_trace_action: 'Copy this run trace id',
    trace_copied: 'trace id copied',
    /** An insecure origin, or a browser that refused: the string is still on screen. */
    clipboard_refused: 'this browser would not give up its clipboard',
    /** A re-run the server accepted without starting anything. */
    nothing_started: (status: string) => `nothing started: ${status}`,
    /** The Step tab, before a node has been chosen on the graph. */
    no_step_chosen: 'No step chosen.',
    graph_empty: "This run's pinned definition has no steps to draw.",

    // The Run tab.

    copy_trace: 'Copy the trace id',
    copy_run_id: 'Copy the run id',
    /** The section holding the run's four instants. */
    timing: 'Timing',
    /**
     * The terms of the panel's definition lists, which are lower case throughout.
     *
     * One term per concept across the three tabs: what a step started is the same question as
     * what a run started, and the word is the same word.
     */
    fact: {
        kind: 'kind',
        by: 'by',
        created: 'created',
        started: 'started',
        finished: 'finished',
        window: 'window',
        pipeline: 'pipeline',
        version: 'version',
        run: 'run',
        trace: 'trace',
        step: 'step',
        block: 'block',
        rule: 'rule',
        /** The steps this one waited for. */
        after: 'after',
        /** How long it sat before a worker took it up. */
        queued: 'queued',
        /** How long it took. */
        took: 'took',
        /** How long it sat parked between probes. */
        waiting: 'waiting',
        /** How many elements a fan-out ran. */
        items: 'items',
    },
    /** Who asked for a run, where the server recorded nobody. */
    trigger_not_recorded: 'not recorded',
    no_parameters: 'This run was started with no parameters.',

    // The Step tab.

    /** The section listing every try the step has had. */
    attempts: 'Attempts',
    no_attempts: 'No attempts.',
    /** Why the config on screen is not the config the run ran under. */
    config_stale: (pinned: string, shown: string) =>
        `This run pinned version ${pinned}; the config below is version ${shown}, which is what the pipeline holds now.`,
    no_config: 'The pipeline document names no config for this step.',
    /** What the config block, and the window it opens in, are called. */
    config_title: (step: string) => `${step} · config`,
    no_output: 'No output.',
    /** What the output block, and the window it opens in, are called. */
    output_title: (step: string) => `${step} · output`,
    no_items: 'No items.',
    fan_out_note:
        'The step after this one reads these as one list, in item order. An item that did not succeed is not in the list.',
    /** Why a fan-out element is missing from that list, said as the state that kept it out. */
    absent: {
        failed: 'failed, so it is not in the list',
        cancelled: 'cancelled, so it is not in the list',
        skipped: 'skipped, so it is not in the list',
        /** Any other state: the element ran and produced nothing. */
        nothing: 'no output',
    },
    /** What one element's output block is called. */
    item_output_title: (step: string, item: string) => `${step} · ${item} · output`,
    /** Which try a row of the attempts list is. */
    attempt_number: (number: string) => `attempt ${number}`,
    /** Added to that row where an operator asked for the try rather than the engine. */
    attempt_asked_for: ', asked for',
    /** Which fan-out element a try ran for. */
    item_label: (item: string) => `item ${item}`,

    // The graph's nodes, and the sentences `lib/run-detail` folds for them.

    /** How wide a fan-out step is, on the node's header. */
    node_items: (count: string) => `${count} items`,
    /** The node's tooltip, where a live wait reports how far it has come. */
    node_hint: (detail: string, percent: string) => `${detail} (${percent}%)`,
    /** One state's tally, for a fan-out too wide to name its elements. */
    node_item_count: (count: string, status: string) => `${count} ${status}`,
    /** What a late grid says where its elements will be: the step whose output sets its width. */
    waits_for: (step: string) => `waits for ${step}`,
    /** The same line for a grid fixed at creation, which waits for nothing. */
    fans_out: 'fans out',
    /** A step that has not started, said as what it is behind. */
    depends_on_note: (steps: string) => `after ${steps}`,
    /** A step whose output went to storage, said as where it went. */
    saves_to: (uri: string) => `saves to ${uri}`,
    /** Which try an element is on, and when its next poll is due. */
    retry_try: (attempt: string) => `try ${attempt}`,
    retry_try_in: (attempt: string, seconds: string) => `try ${attempt} in ${seconds}s`,

    // The Output tab.

    artifacts_reading: 'Reading the artifacts.',
    artifacts_empty: 'No step of this run wrote an output.',
    /** What an artifact the run itself wrote is filed under, where a step's is filed under it. */
    artifact_of_run: 'the run',

    // The Report tab.

    report_pending: 'The report is written when this run settles.',
    report_reading: 'Reading the report.',
    report_download: 'Download the markdown',
    report_missing:
        'This run rendered no report document. A pipeline document declares one under its report key.',
    summary_reading: 'Reading the summary.',
    /** How many warnings one step of the summary wrote. */
    step_warned: (count: string) => `${count} warned`,

    // Why the Run button is shut on the window the dialog asks for.

    window_needed: 'This pipeline needs a window',
    window_half: 'A window has two ends: give both, or neither.',
    window_backwards: 'A window runs forwards: the start is before the end.',
} as const

/**
 * The console across the foot of the run screen, and the log pane inside a step's own tab.
 */
const terminal = {
    // The drawer's chrome.

    /** The accessible name of the drawer itself, which is a landmark. */
    name: 'Run terminal',
    heading: 'Terminal',
    hide: 'Hide the terminal',
    resize: 'Resize the terminal',
    copy_lines: 'Copy the lines on screen',
    download: 'Download every line as NDJSON',

    // The three controls that narrow what is drawn.

    /** The accessible name of the level select. */
    level_filter: 'Least level shown',
    /** Each threshold, said as what it lets through. `LogLevel` is the key. */
    level: {
        debug: 'All levels',
        info: 'Info and up',
        warning: 'Warnings and up',
        error: 'Errors only',
    },
    /** The accessible name of the step select. */
    step_filter: 'Filter by step',
    /** What the step select is worth when no step is chosen. */
    every_step: 'Every step',
    /** The accessible name of the search box. */
    match_filter: 'Filter lines by text',
    match_placeholder: 'Search lines',
    /** How many lines are on screen out of how many the run has written. */
    count_one: (shown: string, total: string) => `${shown} of ${total} line`,
    count_many: (shown: string, total: string) => `${shown} of ${total} lines`,

    // The lines themselves.

    /** The prefix on a line no step wrote: the engine's own, an alert's. */
    run_line: 'run',
    /** The last line, once nothing more is coming and the run's own state is not known. */
    end_of_log: 'end of log',
    /** The same line, stating the state the run settled in. */
    ended: (status: string) => `run ${status}`,
    empty_filtered: 'No line matches these filters.',
    /** Nothing was logged and nothing more will be. */
    empty_settled: 'This run logged nothing.',
    /** Nothing has been logged yet, on a run that could still write. */
    empty: 'Nothing logged.',
    /** The button that appears once the reader has scrolled off the tail. */
    newest: 'Jump to newest',

    // What the copy and the download say when they land.

    copied_one: '1 line copied',
    copied_many: (count: string) => `${count} lines copied`,
    saved: (count: string) => `${count} lines saved`,
    /** A download the server refused with nothing to say for itself. */
    download_failed: 'the server did not answer',

    // The log pane inside a step's tab, where the tense is the step's own.

    /** The step has settled, so what it wrote is the whole of what it will write. */
    step_empty_settled: 'This step wrote nothing.',
    /** The step could still write. */
    step_empty: 'This step has written nothing.',
} as const

/**
 * What the triggers screen says.
 *
 * THREE KINDS, THREE PARALLEL BLOCKS. The screen lists schedules, webhooks and watches under
 * three headings, opens a panel per kind and offers a dialog for the two a person may declare,
 * so the vocabulary is grouped by kind rather than by surface: everything a schedule says is
 * under `schedule`, and the gaps between the blocks are the differences between the kinds.
 *
 * WHAT IS NOT HERE. The nouns the whole product labels things with -- Pipeline, Clock, Timezone,
 * Next, Endpoint, Signature, Rate limit, Step, Cursor, Pinned parameters, Payload mapping -- are
 * `word`, and the chips a trigger wears are `state.armed`. Only this screen's own words are here.
 */
const triggers = {
    /** No trigger of any kind on the instance. */
    empty: 'Nothing fires on its own. A document declares them under its triggers key.',
    /** The palette row that reads the listing again. */
    reload: 'Read the triggers again',
    /** The run a firing or a delivery started, as the link a listing cell draws. */
    run: 'run',
    /** A trigger the pipeline's own document declares, where no triggers document owns it. */
    managed: 'managed',
    /** The one verb a schedule's and a watch's panel offers, in its two directions. */
    pause: 'Pause',
    resume: 'Resume',
    /** The window title over a trigger's pinned parameters. */
    pinned_title: (code: string) => `${code} · pinned parameters`,

    /** The clocks. */
    schedule: {
        /** The header button, the palette row, and the dialog's own title. */
        new: 'New schedule',
        heading: 'Schedules',
        empty: 'No schedules. A document declares one under its triggers key.',
        /** What the foot counts. `rowsRead` takes the plural off it, so it is written plural. */
        noun: 'schedules',
        /** The column of what the schedule last did. */
        last_firing: 'Last firing',
        /** That column, for a schedule nothing has fired yet. */
        never_fired: 'never fired',
        /** The same moment as the panel's own fact. */
        last_fired: 'Last fired',
        /** An interval clock, drawn as what it repeats. */
        every: (interval: string) => `every ${interval}`,
        /** A row that arrived with none of the three clock fields filled in. */
        no_clock: 'no clock',
        /** A one-time clock whose moment has gone by, said in front of the instant. */
        fired: 'fired',
        /** A clock that names no further moment, where the next firing would be. */
        nothing_scheduled: 'nothing scheduled',
        /** The panel's history of what the schedule has actually done. */
        firings: 'Firings',
        /** That history, for a schedule that has done nothing. */
        not_fired: 'Not fired.',
        /** What one firing was due for, beside the outcome it had. */
        due: (when: string) => `due ${when}`,
        /** A firing the scheduler reached late, said around the outcome it still had. */
        misfired: (outcome: string) => `${outcome} (misfired)`,
        /** The dialog that declares one. */
        dialog: {
            code_hint: 'nightly',
            description_hint: 'What this clock is for',
            /** Which clock a new schedule is declared with, keyed by the field it fills in. */
            clock: {
                cron: {
                    name: 'Cron',
                    hint: '0 5 * * *',
                },
                interval: {
                    name: 'Interval',
                    hint: '15m',
                },
                at: {
                    name: 'One time',
                    hint: '2026-06-01T09:00:00Z',
                },
            },
            timezone_hint: 'Search by zone or offset',
            /** What goes where the next firings would, when the parser said nothing of its own. */
            unreadable_clock: 'This clock cannot be read.',
            /** Why Create is shut: no pipeline, no code, no clock, or parameters that do not fit. */
            no_pipeline: 'A schedule fires one pipeline, and this one names none.',
            no_code: 'A schedule is addressed by its code, and this one has none.',
            no_clock: 'Nothing says when this fires.',
            params_refused: 'A pinned parameter is not what this pipeline takes.',
        },
    },

    /** The inbound endpoints. */
    webhook: {
        /** The header button, the palette row, and the dialog's own title. */
        new: 'New webhook',
        heading: 'Webhooks',
        empty: 'No webhooks.',
        /** What the foot counts. `rowsRead` takes the plural off it, so it is written plural. */
        noun: 'webhooks',
        /** Where a caller posts, as the listing cell and the panel fact both spell it. */
        post: (path: string) => `POST ${path}`,
        /** Whether a delivery is proved to have come from who it says. */
        signed: 'HMAC',
        unsigned: 'unsigned',
        /** The rate limit's column, which is narrower than the noun. */
        rate: 'Rate',
        /** The rate limit in the listing, and the same number as the panel's fact. */
        rate_per_minute: (count: string) => `${count}/min`,
        rate_a_minute: (count: string) => `${count} a minute`,
        /** When something last arrived: the listing's column and the panel's fact. */
        last_delivery: 'Last delivery',
        /** The verbs on whether the endpoint answers at all. */
        enable: 'Enable',
        disable: 'Disable',
        /** Minting a new token, and what that costs. */
        rotate: 'Rotate token',
        rotate_warning:
            'Rotating creates a new token and forgets the old one immediately. Every caller has to be updated.',
        /** The window title over a webhook's payload mapping. */
        mapping_title: (code: string) => `${code} · payload mapping`,
        /** The panel's history of what has arrived. */
        deliveries: 'Deliveries',
        /** That history, for a webhook nothing has been sent to. */
        nothing_delivered: 'Nothing delivered.',
        /** Who sent one delivery, where the delivery says. */
        from: (source: string) => `from ${source}`,
        /** The dialog that declares one. */
        dialog: {
            code_hint: 'upstream-publish',
            description_hint: 'What sends to this endpoint',
            /** A parameter the pipeline will not run without, under its name in the mapping. */
            required: 'required',
            /** What is typed against each parameter: a path into the payload. */
            path_hint: '$.',
            mapping_note:
                'One JSONPath per parameter the pipeline declares. Anything else in the payload is ignored.',
            secret: 'Signing secret',
            secret_hint: 'Leave empty for an unsigned endpoint',
            rate: 'Deliveries a minute',
            /** Said beside Create, because the token is answered once and never again. */
            token_once: 'Its token is shown once, after Create.',
            /** Why Create is shut. */
            no_pipeline: 'A webhook fires one pipeline, and this one names none.',
            no_code: 'A webhook is addressed by its code, and this one has none.',
        },
        /** The one moment a minted token is readable. */
        token: {
            title: (code: string) => `The token for ${code}`,
            note: 'This instance keeps only its hash. This is the only time it can be read; rotating the webhook is how a lost token is replaced.',
            copy: 'Copy token',
            copied: 'Copied',
            /** Over the path a caller is configured with. */
            url: 'Where to POST',
        },
    },

    /**
     * The sensors. A watch is only ever declared by a document, so there is no dialog and no
     * New: what this block holds is the listing, the panel, and the words a wait is in.
     */
    watch: {
        heading: 'Watches',
        empty: 'No watches. A document declares one under its triggers key.',
        /** What the foot counts. `rowsRead` takes the plural off it, so it is written plural. */
        noun: 'watches',
        /** What the watch has waiting on its sensor now. */
        waiting: 'Waiting',
        /** Why the last wait ended without the sensor succeeding. */
        last_error: 'Last error',
        /** How many waits in a row have ended that way. */
        failures: 'Failures in a row',
        /** A watch held back after a failure, said in front of the instant it arms at. */
        backing_off_until: 'backing off until',
        /** Nothing waiting and nothing holding it back: the next tick arms it. */
        arming: 'arming',
        /** The window title over where the watch has read up to. */
        cursor_title: (code: string) => `${code} · cursor`,
    },

    /** A trigger's own history at the foot of its panel, one page at a time. */
    history: {
        loading: 'Reading from the server',
        more: 'Load more',
        /** The same button while the next page is in flight. */
        more_busy: 'Reading',
    },

    /** What both new-trigger dialogs say, whichever kind is being declared. */
    dialog: {
        pipeline_hint: 'Search by name or code',
        name_hint: 'What to call it on screen',
        /** Create, while the declaration is in flight. */
        creating: 'Creating',
        /** The priority row that declares none, so the pipeline's own is what a run takes. */
        priority_inherited: "The pipeline's",
        /** Which reading of the pinned parameters is in front of somebody. */
        params_written: 'How the parameters are written',
        params_form: 'Form',
        params_json: 'JSON',
        /** The JSON reading's box, for whoever is not looking at it. */
        params_json_label: 'Pinned parameters as JSON',
        /** Why a parameters box is empty: nothing to fill in yet, or nothing to fill in at all. */
        no_pipeline: 'No pipeline chosen.',
        no_params: 'This pipeline takes no parameters.',
        /** What a box of JSON that is not the parameters says: unparseable, or not an object. */
        params_unreadable: 'this is not JSON',
        params_not_object: 'The parameters are a JSON object.',
    },
} as const

/**
 * What the connections screen says: the listing, the form beside it, and the dialog that mints one.
 *
 * THE FOUR HEALTH WORDS ARE NOT HERE. A credential's health is `state.health`, which the row, the
 * form and the dashboard all read; nothing in this section spells one a second time.
 */
const connections = {
    /** The dialog that mints a credential, and the two controls that open it. */
    new: 'New connection',
    /** The palette's row for reading the listing again. */
    reload: 'Read the connections listing again',
    /** What the table counts in its footer. */
    noun: 'connections',
    empty: 'No connections.',
    /** The row's button, which asks the external system again. */
    check_row: (code: string) => `Check ${code}`,

    /** The one clause every screen states a set of connections' health in. */
    note: {
        /** `noun` carries its own leading space, and is empty where the subject is connections. */
        healthy: (healthy: string, total: string, noun: string) => `${healthy} of ${total}${noun} healthy`,
        unverified: (many: string) => `${many} could not be verified`,
        never_checked: {
            one: (many: string) => `${many} has never been checked`,
            many: (many: string) => `${many} have never been checked`,
        },
    },

    /** A connection whose config carries nothing the summary line can name. */
    no_settings: 'no settings',
    /** The settings the summary line had no room for. */
    more_settings: (many: string) => `+${many} more`,

    /** The form beside the listing: the word before the instant of the last check. */
    checked_at: 'checked',
    /** What follows the created instant when the record has been edited since. */
    also_updated: ' · updated ',
    name_placeholder: 'What to call this on screen',
    /** Under the name box: what a name is not, and what a reference uses instead. */
    name_hint: (code: string) => `Display only. Every reference to this credential is by its code, ${code}.`,
    description_placeholder: 'What this credential is for. Markdown is rendered.',
    /** The heading over the controls the kind's own schema built. */
    settings_heading: 'Settings',
    /** Why Save is shut. */
    settings_refused: 'A setting above is not what this kind accepts.',
    /** The Save button while the edit is in flight. */
    saving: 'Saving',
    /** Beside Save once the edit has been written. */
    saved: 'Saved.',

    /** The dialog that mints one, under its title. */
    sealed: 'Secret fields are sealed on the way in and never read back out.',
    /** An example of the shape a code is typed in. */
    code_placeholder: 'playground',
    /** The kind box before anything is chosen. */
    choose_kind: 'Choose a kind',
    new_name_placeholder: 'What to call it on screen. Optional; nothing references it.',
    /** The Create button while the connection is being minted. */
    creating: 'Creating',
    /** Why Create is shut, in the order the dialog decides it. */
    needs_code: 'A connection is addressed by its code, and this one has none.',
    needs_kind: 'No kind is chosen, and a connection is a credential of one kind.',
    unreadable_setting: 'A setting below holds text that is not a value.',
    new_settings_refused: 'A setting below is not what its kind accepts.',

    /** A write-only password box, which says whether the instance already holds one. */
    secret_stored: 'stored — typing replaces it, blank keeps it',
    secret_unset: 'not set — type to set one',
} as const

/**
 * What the blocks screen says: the catalog's own listing, the three registries under it, and the
 * reference panel that states what one entry takes.
 */
const blocks = {
    /** The box the whole catalog is narrowed in. */
    search: 'Search blocks by id or summary',
    /** Nothing installed, which is an instance with no plugins rather than a filter that found none. */
    empty: 'No blocks installed — plugins contribute them.',
    empty_filtered: 'Nothing in the catalog matches that.',
    /** What the catalog's tables count in their footer. */
    noun: 'blocks',

    /** The column counting the shipped documents that use a block. */
    examples_header: 'Examples',
    /** The count itself, which is the link to those documents. */
    example_count: {
        one: (many: string) => `${many} example`,
        many: (many: string) => `${many} examples`,
    },
    example_link: (block: string) => `The shipped documents that require ${block}`,

    /**
     * The supporting registries, each a heading over its own table and the panel's tab.
     *
     * The key is the registry's, not the wire's: `GET /blocks` answers `storage_schemes`,
     * `notifiers` and `connection_kinds`, and this screen shelves each under one of these.
     */
    registry: {
        scheme: {
            title: 'Storage schemes',
            noun: 'schemes',
        },
        notifier: {
            title: 'Notifiers',
            noun: 'notifiers',
        },
        connection: {
            title: 'Connection kinds',
            noun: 'connection kinds',
        },
    },
    /** A registry row's title column, which holds an id and the line its schema opens with. */
    entry_header: 'Entry',
    /** A registry entry whose kind's schema declares no fields. */
    entry_no_config: 'This takes no configuration.',

    /** The section over what the catalog says about a block besides its schemas. */
    facts_section: 'Facts',

    /**
     * One block's declared facts, as the rows of a definition list.
     *
     * THE TERMS ARE THE WIRE'S OWN KEYS, DRAWN RAW. Somebody reading this is reading the answer
     * `GET /blocks` gave, so the term is the member's name and a prettier word would teach a name
     * that appears nowhere. The details beside them are this product's words, and the seconds a
     * default is stated in are `measure.seconds`.
     */
    fact: {
        term: {
            plugin: 'plugin',
            idempotent: 'idempotent',
            local_execution: 'local_execution',
            default_poll_seconds: 'default_poll_seconds',
            default_deadline_seconds: 'default_deadline_seconds',
        },
        idempotent: {
            yes: 'yes',
            no: 'no',
        },
        /** Whether an instance has to allowlist the block's id before a step may name it. */
        local_execution: {
            required: 'requires allowlisting',
            absent: 'no allowlist entry',
        },
    },

    /** A block whose config schema declares no fields. */
    block_no_config: 'This block takes no configuration.',

    /**
     * The shape one config key takes, in the words the schema is written in.
     *
     * Keyed by what `lib/schema-form` read the field as, which is what a control is chosen by
     * where there is a control; two of them are the same word because a program is a string.
     */
    field_type: {
        text: 'string',
        code: 'string',
        number: 'number',
        integer: 'integer',
        switch: 'boolean',
        select: 'enum',
        pairs: 'map',
        json: 'json',
    },
    /** A field carrying a program, which states the language beside the shape. */
    field_type_media: (shape: string, media: string) => `${shape} (${media})`,
    /** A field the schema also allowed null for. */
    field_type_nullable: (shape: string) => `${shape} or null`,
    /** Beside a key a document has to carry. */
    field_required: 'required',
    /** Before what a key falls back to when a document leaves it out. */
    field_default: 'default',
    /** How much config a block takes, for the column that says so at a glance. */
    config_fields: {
        one: (many: string) => `${many} field`,
        many: (many: string) => `${many} fields`,
    },
} as const

/** What the examples listing, the filters over it and the panel beside it say. */
const examples = {
    /** The palette row that narrows the listing to what may be copied. */
    show_starters: 'Show only the starters',
    /** The palette row that takes every filter off. */
    clear_filters: 'Clear the filters on the examples listing',
    /** How much of the corpus the filters left, drawn only where they left less than all of it. */
    counted_of: (shown: string, total: string) => `${shown} of ${total}`,
    search: 'Search examples by code, name, description or tag',

    /** The two-value filter over the corpus. */
    which: {
        label: 'Which documents',
        all: 'All',
        starters: 'Starters',
    },
    any_shelf: 'Any shelf',
    any_plugin: 'Any plugin',
    /** The chip that takes off the narrowing the Blocks screen linked here with. */
    stop_narrowing: (block: string) => `Stop narrowing to ${block}`,

    /** No plugin contributed anything. */
    none_installed: 'No examples installed — plugins contribute them.',
    /** The filters left nothing. */
    none_match: 'Nothing in the corpus matches that.',
    /** Nothing to show, with nothing being narrowed. */
    empty: 'No examples.',
    /** What the listing's footer counts its rows in. */
    noun: 'examples',

    /** The mark a document that may be copied wears, on the row and in the panel. */
    starter_badge: 'Starter',
    /** Why a document that carries a section states it. */
    carries_hint:
        'An instance refuses a document that carries these, so a copy names them under requires instead.',
    /** What a document carries rather than requires, said on the row. */
    carries: (sections: string) => `carries ${sections}; a copy names them`,

    /** What a document needs of an instance, as the listing's column reads it. */
    requirement: {
        /** A count and the noun it is counted in. */
        counted: (count: string, noun: string) => `${count} ${noun}`,
        /** The counts, and how many of them are not here. */
        missing: (counted: string, missing: string) => `${counted}, ${missing} missing`,
        /** How each kind is counted, singular and plural. Keyed by `Need`. */
        count: {
            connection: {
                one: 'connection',
                many: 'connections',
            },
            schema: {
                one: 'schema',
                many: 'schemas',
            },
            pipeline: {
                one: 'pipeline',
                many: 'pipelines',
            },
            storage: {
                one: 'storage scheme',
                many: 'storage schemes',
            },
            block: {
                one: 'block',
                many: 'blocks',
            },
            worker: {
                one: 'worker tag',
                many: 'worker tags',
            },
        },
        /** What one requirement is called on its own line in the panel. Keyed by `Need`. */
        line: {
            connection: 'connection',
            schema: 'schema',
            block: 'block',
            pipeline: 'pipeline',
            storage: 'storage',
            worker: 'worker tag',
        },
        /** Whether this instance holds one: nothing here can say, it does, it does not. */
        unchecked: 'not checked',
        here: 'here',
        missing_word: 'missing',
    },

    /** The panel's own sections. */
    facts: 'Facts',
    /** The facts' terms, which are the wire's words rather than the product's nouns. */
    fact: {
        plugin: 'plugin',
        shelf: 'shelf',
        path: 'path',
    },
    /** Where a document filed at the top of a distribution's shelves sits. */
    root_shelf: 'the root',
    requires_nothing: 'This document requires nothing in particular of an instance.',
    /** What the read-only editor holding the document is called, in place and in a window. */
    source_pane: 'The document',
    source_pane_windowed: (name: string) => `${name}, in a window`,
    /** The button that copies a starter into the editor. */
    use_as_starter: 'Use as starter',
} as const

/** What the schemas screen says: the listing, the schema in the panel, and the dialog that writes one. */
const schemas = {
    /** The dialog that stores a shape, and the two controls that open it. */
    new: 'New schema',
    /** The palette's row for reading the listing again. */
    reload: 'Read the schemas listing again',
    /** What the table counts in its footer. */
    noun: 'schemas',
    empty: 'No schemas.',
    /** How many shapes this instance holds, which the screen states under its heading. */
    count: {
        one: (many: string) => `${many} schema`,
        many: (many: string) => `${many} schemas`,
    },
    /** Over the schema body in the panel. */
    body_title: (code: string) => `${code} · schema`,
    /** The Delete button while the schema is being removed. */
    deleting: 'Deleting',

    /**
     * The dialog's line, written around the three JSON Schema keywords it names.
     *
     * The keywords are drawn in the code face between these two fragments, so they are the
     * standard's words rather than this product's and are not part of either.
     */
    identity: {
        lead: "Its code, title and description come from the schema's own",
        and: ' and ',
    },
    /** What the editor is called, for whoever is not reading the screen. */
    editor_label: 'the schema',
    /** The code box, which is only for a schema that names no `$id`. */
    code_placeholder: 'taken from $id when left blank',
    /** Write the shape to the instance. */
    store: 'Store',
    /** The Store button while the schema is being written. */
    storing: 'Storing',
    /** A body the browser could not read as JSON, said where it was typed. */
    unreadable: (error: string) => `The schema is not readable JSON: ${error}`,
} as const

/**
 * What the accounts screen says: the two listings, the panel one account is changed in, and the
 * three dialogs it opens. The words for an account that is switched off and a token that no
 * longer opens anything are `state.armed`, not here.
 */
const users = {
    /** The palette row that opens the new-account dialog. */
    new_user_action: 'Create an account',
    /** The palette row that opens the new-token dialog. */
    new_token_action: 'Mint an automation token',
    /** The palette row that reads both listings again. */
    reload_action: 'Read the accounts listing again',

    /** The button above the listing, and the title of the dialog it opens. */
    new_account: 'New account',
    accounts_heading: 'Accounts',
    accounts_empty: 'No accounts.',
    /** The plural the accounts listing's footer counts its rows in. */
    accounts_noun: 'accounts',
    /** Whether the account can still sign in. */
    active_column: 'Active',
    last_signed_in_column: 'Last signed in',

    /** The panel's line of dates, where the account has never signed in. */
    never_signed_in: 'never signed in',
    /** The same line, where it has. The moment itself follows. */
    last_signed_in: 'last signed in',
    name_placeholder: 'What to call this account on screen',
    /** Under the name field: that the name carries no identity and the username does. */
    name_hint: (username: string) =>
        `Display only. This account signs in as ${username}, and that is what every reference to it is by.`,
    /** The placeholder on a field that may be left blank. */
    optional: 'Optional',
    email_hint: 'Unique across accounts.',
    /** What each role may do, in the one line the radio row says under its name. */
    role_hint: {
        admin: 'Everything, including accounts, tokens and connections.',
        operator: 'Define, run and observe pipelines.',
        viewer: 'Read what this instance holds, and change nothing.',
    },
    /** The one button that turns an account off, or back on. */
    deactivate: 'Deactivate',
    activate: 'Activate',
    /** The panel's button, and the title of the dialog it opens. */
    reset_password: 'Reset password',
    /** The button above the tokens listing, in the panel, and the title of the dialog they open. */
    new_token: 'New token',

    tokens_heading: 'Tokens',
    /** Under that heading: that a signed-in session is not one of these. */
    tokens_hint: 'A session is never listed here.',
    tokens_empty: 'No tokens.',
    /** The plural the tokens listing's footer counts its rows in. */
    tokens_noun: 'tokens',
    last_used_column: 'Last used',
    /** The accessible name of a row's revoke button, which the row itself does not repeat. */
    revoke_row: (token: string) => `Revoke ${token}`,

    /** Under the new-account dialog's title. */
    new_account_hint: 'The password is what it signs in with the first time.',
    /** Refused in the browser, so a password the server was always going to refuse never leaves it. */
    password_too_short: (minimum: string) => `A password must be at least ${minimum} characters.`,

    /** Under the new-token dialog's title, where the token is the caller's own. */
    token_scope_self: 'It holds whatever this account holds.',
    /** The same line, where the token is minted for another account. */
    token_scope_for: (username: string) => `It holds whatever ${username} holds.`,
    token_name_placeholder: 'ci-deploy',
    token_name_hint: 'Lower case, digits and single hyphens. It is what the token is revoked by.',
    /** Beside the secret, which the server answers once and cannot answer again. */
    token_once: 'This is the only time this token will be shown.',
    copy_token: 'Copy the token',
    /** The copy button, before and after the secret reached the clipboard. */
    copy: 'Copy',
    copied: 'Copied',

    /** Under the reset-password dialog's title: what setting a password does to what is open. */
    reset_password_hint: (username: string) =>
        `${username} is signed out everywhere and its tokens keep working.`,
    new_password: 'New password',
} as const

/**
 * What the worker registry says: the screen, and the table the dashboard draws from the same
 * component. The sentence each of the five concerns says is `state.worker`, not here.
 */
const workers = {
    /** The plural the listing's footer counts its rows in. */
    noun: 'workers',
    /** The palette row that reads the registry again. */
    reload_action: 'Read the worker registry again',
    empty: 'No workers. Start one with dg worker; nothing is claimed until one registers.',
    /** The note along the foot of the screen when no worker has anything to report. */
    all_answering: 'every worker is answering',
    /** One worker's concern, named with the worker it belongs to. */
    concern_note: (worker: string, concern: string) => `${worker} ${concern}`,
    /** How long ago a worker the server has stopped hearing from was last heard from. */
    last_seen_ago: (ago: string) => `last seen ${ago}`,
    /** The badge beside the state of a worker running a catalog this server does not have. */
    mismatch_badge: 'different catalog',
    /** That badge's tooltip, where the worker named no catalog at all. */
    no_digest: 'no catalog digest reported',
} as const

/**
 * The alerting screen: the rules that watch runs, the channel strip above them, the delivery
 * queue below, and the two dialogs that declare a rule and prove a channel.
 */
const alerting = {
    /** The rows the palette offers for this screen, each longer than the button that does the same. */
    palette: {
        new_rule: 'New alert rule',
        send_test: 'Send a test through a channel',
        reload: 'Read the alert rules again',
    },

    /** The header's primary verb, and the title of the dialog it opens. */
    new_rule: 'New rule',
    rules_heading: 'Rules',
    rules_empty: 'No rules.',
    /** The noun the rules table counts its rows in, which the count singularises itself. */
    rules_noun: 'rules',
    notifications_heading: 'Notifications',
    notifications_empty: 'Nothing queued.',
    /** The noun the notifications table counts its rows in. */
    notifications_noun: 'notifications',
    /** The queue's filters, when neither narrows anything. */
    any_status: 'Any status',
    any_notifier: 'Any notifier',
    /** Which sender a message left by, as the queue's filter names it. */
    notifier: 'Notifier',

    /** The strip above the tables: where an alert can go, and whether it still can. */
    channels_heading: 'Channels',
    /** A read that has not answered yet, said where the answer will be. */
    reading: 'Reading from the server',
    /** No notifier at all is installed, so there is nowhere for an alert to go. */
    channels_none: 'No channel is installed.',
    /**
     * The two words the strip adds to a connection's own health vocabulary, which the rest of a
     * channel's states are drawn from.
     */
    channel: {
        /** The process log, which needs no credential and which nothing checks. */
        ready: 'ready',
        /** A notifier this instance installed and holds no credential for. */
        not_set_up: 'not set up',
    },
    /** The way in to minting the credential a channel with none is waiting for. */
    set_up_channel: (notifier: string) => `Set up ${notifier}`,

    /** What each event is called wherever a rule names one. Keyed by `AlertEvent` on the wire. */
    event: {
        run_failed: 'Failed',
        run_completed_with_errors: 'Completed with errors',
        run_succeeded: 'Succeeded',
        run_stuck: 'Stuck',
    },
    /** How wide a rule reaches, keyed by `AlertScope`, as the dialog's control offers the two. */
    scope: {
        global: 'Every pipeline',
        pipeline: 'One pipeline',
    },
    /** A rule that names no pipeline, in the scope column and in the phrase a rule is matched by. */
    every_pipeline: 'every pipeline',
    /** The floor a rule fires at, beside the scope rather than in a column of its own. */
    importance_floor: (importance: string) => `${importance} and above`,
    /** What one rule matches, said in one phrase. */
    match_note: (event: string, where: string) => `${event} — ${where}`,
    /** When a rule last delivered anything. */
    last_sent: 'Last sent',
    /** Hold a rule's deliveries, or let them resume. */
    pause: 'Pause',
    resume: 'Resume',
    /** The panel's list of what this rule has sent lately. */
    recent_deliveries: 'Recent deliveries',
    deliveries_empty: 'Nothing sent.',

    /** When the message was put on the queue, which is the row's own `created_at`. */
    queued_at: 'Queued',
    /** When a worker got it through. */
    sent_at: 'Sent',
    /** When a worker will try a message that has not got through yet. */
    next_try: 'Next try',
    /** How many tries there have been, and how many the instance allows. */
    attempts: 'Attempts',
    attempts_of: (attempt: number, allowed: number) => `${attempt} of ${allowed}`,
    /** The same count where the column has room for the noun. */
    attempts_counted: (attempt: number, allowed: number) => `${attempt} of ${allowed} attempts`,
    /** What raised the message. */
    raised_by: 'Raised by',
    /** What raised a message nothing declared: somebody proving a channel. */
    raised_by_test: 'a test, not a rule',
    /** The channel's own sentence about why it refused. */
    channel_said: 'What the channel said',
    /** Why there is no history under that sentence: the row carries one error and a count. */
    latest_refusal_only: 'Only the latest refusal is kept. Earlier attempts are counted, not stored.',
    open_run: 'Open the run',
    /** A message no run is behind, in the run cell. */
    no_run: 'no run',
    /** A run whose pipeline the row does not carry, named by what it is rather than by its id. */
    a_run: 'a run',

    /** The boxes both dialogs draw, and what each one shows before anything is typed. */
    code_placeholder: 'ops-slack-failed',
    name_placeholder: 'Tell the ops channel',
    description_placeholder: 'What this rule is for',
    pipeline_search: 'Search by name or code',
    /** Only pipelines at or above the chosen floor. */
    importance_hint: 'Only pipelines that matter at least this much.',
    /** What the control answers with when a rule fires whatever the pipeline is worth. */
    importance_any: 'Any',
    /** The one target a rule or a test names, as the picker asks for it. */
    deliver_through: 'Deliver through',
    target_search: 'Search by name, kind or code',
    /** The one channel with no credential behind it, as the picker's first row. */
    log_target: 'The process log',

    /**
     * The subject and the body, which are Jinja rather than English: the braces are what the
     * template engine reads, and a translation keeps them exactly as they stand.
     */
    subject_placeholder: '{{ run.pipeline }} run {{ run.status }}',
    body_placeholder: '{{ run.pipeline }} ended {{ run.status }}: {{ run.url }}',
    /** The run's facts a subject may reach for, which are the wire's own field names. */
    subject_references: 'pipeline, status, id, error, trigger, duration_ms and url',
    subject_hint: (references: string) => `A Jinja template: {{ run.* }} reads the run's ${references}.`,
    body_hint: "A Jinja template over the run's facts; report is the run's report document when it has one.",
    /** What the body pane is called: the window's title, and what a screen reader hears. */
    body_pane: 'body',
    /** The same buffer, named by the pane the window draws it in. */
    body_pane_windowed: (name: string) => `${name}, in a window`,
    /** How long a rule waits before it fires again, as the box shows a duration. */
    throttle_placeholder: '15m',
    /** The footer of the new-rule dialog, which declares and does not send. */
    declare_only: 'A rule fires when a run settles. Nothing is sent now.',
    /** The primary verb while the request is in flight. */
    creating: 'Creating',
    saving: 'Saving',

    /** Why Create is shut on a new rule, in the order somebody fills the form in. */
    unready: {
        code_missing: 'A rule is addressed by its code, and this one has none.',
        code_shape: 'A code is lowercase words joined by - or _.',
        pipeline_missing: 'A rule watching one pipeline names that pipeline, and this one names none.',
        throttle_shape: 'A throttle is a duration, such as 15m.',
    },

    /** What sending a test amounts to, under the dialog's title. */
    test_explained: 'The message goes through the same queue a real alert does, and a worker delivers it.',
    send: 'Send',
    /** The same verb once one message has already gone. */
    send_again: 'Send again',
    /** Show the message the dialog is watching in the queue behind it. */
    open_in_queue: 'Open in the queue',
    /** Where the message got to, as the dialog watches the row settle. */
    delivered: 'Delivered',
    queued_for_worker: 'Queued for the next worker pass.',
    given_up: (attempt: number, allowed: number) => `Given up after ${attempt} of ${allowed} attempts.`,
    /** One try behind us, and the moment of the next, which the sentence is finished with. */
    attempt_of: (attempt: number, allowed: number) => `Attempt ${attempt} of ${allowed}, next try`,
} as const

/**
 * What the settings dialog says, and the shapes the formatters write a measured value in.
 *
 * THE ROWS ARE A TABLE ALREADY. `lib/settings` holds every row as a record, so what is here is
 * that table's two drawn columns -- the label and the fact the few rows that carry one add --
 * with the search box and each pane's own controls around them.
 */
const settings = {
    title: 'Settings',
    search: 'Search the settings',
    /** No row anywhere answers what was typed. */
    no_match: 'Nothing matches that.',

    /** The headings the left nav lays its categories out under. */
    group: {
        preferences: 'Preferences',
        you: 'You',
        instance: 'This instance',
    },

    /** The left nav's entries. The Account entry is `word.account`. */
    category: {
        general: 'General',
        theme: 'Theme',
        shortcuts: 'Shortcuts',
        server: 'Server',
    },

    /** What each row is called, where the word is this dialog's rather than the product's. */
    row: {
        appearance: 'Appearance',
        palette: 'Palette',
        follow_logs: 'Follow logs',
        current_line: 'Current line',
        signed_in_as: 'Signed in as',
        session: 'Session',
        blocks: 'Blocks',
        plugins: 'Plugins',
    },

    /** The fact a row adds where its control cannot show one. */
    description: {
        timezone: 'Timestamps everywhere; a schedule keeps its own.',
        current_line: 'Every editor, in place and in a window, including read-only ones.',
    },

    /** The accessible name of the Timezone row's control, which is not the row's own word. */
    times_control: 'Times',
    /** The reader's own clock, which the other half of that control calls `measure.utc`. */
    times_local: 'Local',
    /** Whether a log pane opens stuck to the newest line. */
    following: 'Following',
    not_following: 'Not following',
    /** Whether an editor marks the row the caret is on. */
    highlighted: 'Highlighted',
    not_highlighted: 'Not highlighted',
    /** Where a username is drawn and nothing is signed in. */
    nobody: 'nobody',

    /** Changing this account's password, in the row that offered to. */
    current_password: 'Current password',
    new_password: 'New password',
    change_password: 'Change password',
    password_changed: 'Password changed. Every other session of this account is signed out.',

    /** Where the keys this app answers apply. */
    shortcuts_apply: 'Anywhere but inside a text box.',

    /** When the readiness probe last answered. */
    checked: (when: string) => `checked ${when}`,
    /** A server fact whose read has not landed. */
    reading: 'Reading',
    documentation: 'Documentation',
    api_reference: 'API reference',

    /** A size at a larger unit, which carries the space `measure.sized` does not. */
    sized: (value: string, unit: string) => `${value} ${unit}`,
} as const

export const LABELS = {
    action,
    word,
    state,
    measure,
    screen,
    shell,
    palette,
    refusal,
    login,
    dashboard,
    pipelines,
    editor,
    form,
    reference,
    runs,
    terminal,
    triggers,
    connections,
    blocks,
    examples,
    schemas,
    users,
    workers,
    alerting,
    settings,
} as const satisfies Record<string, Catalogue>

/**
 * Every label in the product, as code -> label.
 *
 * The walk `Catalogue.all` is on the server: one call reaches every string, so a test can hold
 * all of them to one rule at once, and a translation can be checked for completeness against a
 * list rather than against the source.
 */
export function everyLabel(): Map<string, Label> {
    const found = new Map<string, Label>()
    const walk = (table: Catalogue, prefix: string) => {
        for (const [name, held] of Object.entries(table)) {
            const code = prefix === '' ? name : `${prefix}.${name}`
            if (typeof held === 'string' || typeof held === 'function') found.set(code, held)
            else walk(held, code)
        }
    }
    walk(LABELS, '')
    return found
}
