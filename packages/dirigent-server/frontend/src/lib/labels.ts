/**
 * Every word this interface says to a person, each under a code.
 *
 * THE SAME SHAPE AS THE SERVER'S. `dirigent_common.messages` holds one `Catalogue` per area,
 * mints a dotted code per message, refuses a duplicate name, and keeps `Catalogue.all` so one
 * test can walk every string in the process at once. This is that, in TypeScript's idiom: a
 * section per area, the path through `LABELS` as the code, a duplicate name refused by the
 * compiler rather than at import, and `everyLabel` as the walk. A refusal the server sends
 * arrives with its own code on it, and `refused` is this interface's sentence for that code:
 * the server's English is the fallback for a code with no entry, not what a person reads.
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
 *
 * A VERB'S OWN CONTROL HAS STATES, AND THEY SIT UNDER IT. The word on the button, the word while
 * the request is in flight and the word once it has landed are one concept: `verb`, `busy` and
 * `done` beneath one code, rather than a `Creating` minted again in every section that writes
 * something. A verb with one state is still one string.
 */
const action = {
    /** Leave a dialog that would have written something, writing nothing. */
    cancel: 'Cancel',
    /** Leave a dialog that has already done what it was opened for. */
    close: 'Close',
    /** Leave a dialog whose work is finished and whose answer has been read. */
    done: 'Done',
    /** Write the new thing the dialog was opened to make. */
    create: {
        verb: 'Create',
        busy: 'Creating',
    },
    /** Write the edits made to a thing that already exists. */
    save: {
        verb: 'Save',
        busy: 'Saving',
        done: 'Saved.',
    },
    /** Replace what is stored with what is in front of the reader. */
    update: {
        verb: 'Update',
        busy: 'Updating',
    },
    /** Write a shape to the instance, which is what a schema is created by. */
    store: {
        verb: 'Store',
        busy: 'Storing',
    },
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
    delete: {
        verb: 'Delete',
        busy: 'Deleting',
    },
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
    /** Read again what is already on screen. */
    refresh: 'Refresh',
    /** Mint a value the person should not have to invent. */
    generate: 'Generate',
    /** Put a value on the clipboard, and say so once it is there. */
    copy: {
        verb: 'Copy',
        done: 'Copied',
    },
    /** Hold what a thing fires or delivers, and let it go again. */
    pause: 'Pause',
    resume: 'Resume',
    /** Answer what arrives, or answer nothing. */
    enable: 'Enable',
    disable: 'Disable',
    /** Let an account sign in, or stop it. */
    activate: 'Activate',
    deactivate: 'Deactivate',
    /** Send one message through a channel to see whether it arrives. */
    send_test: 'Send a test',
    /** Try the delivery that failed once more, now. */
    retry_now: 'Retry now',
    /** Begin a session. */
    sign_in: {
        verb: 'Sign in',
        busy: 'Signing in',
    },
    /** End this session. */
    sign_out: 'Sign out',
} as const

/**
 * The nouns this product labels things with.
 *
 * ONE NOUN, ONE ENTRY. The same word is a field's label, a column's header and a card's term,
 * and it is one word in all three places or the product has two names for one thing. A noun
 * that only one screen ever draws stays on that screen's section instead.
 *
 * THE CASE BELONGS TO THE SURFACE, NOT TO THE WORD. A field's label, a column header and a
 * section heading are Sentence case; a definition-list term and a fragment inside a sentence are
 * lower case. A noun this product draws in more than one of those holds each form it actually
 * draws -- `label` for the singular a control or a column wears, `heading` for the plural over a
 * section or a table, `term` for the lower-case singular, `count` for the sentence a listing's
 * foot counts in -- and a form nothing draws is not written down. Nothing derives one form
 * from another: capitalising in code compiles English's own rule into the app.
 *
 * A COUNTED SURFACE HOLDS BOTH NUMBERS. `count` is a `{one, many}` pair, so a foot counting one
 * row says "1 watch" because the word is written there and not because anything took the plural
 * apart. A word that also stands alone in a sentence is written again under `term`, which is a
 * surface of its own: the two are the same string in English and need not be in another
 * language.
 */
const word = {
    /** The addressable key, unique and constrained. */
    code: 'Code',
    /** The optional human title, which carries no identity at all. */
    name: {
        label: 'Name',
    },
    /** The long-form, markdown-capable text. */
    description: 'Description',
    /** What family a thing belongs to. */
    kind: {
        label: 'Kind',
        term: 'kind',
    },
    /** Whichever state machine's word applies. */
    status: 'Status',
    /** The state a rule, a trigger or an account is in, as distinct from its last delivery. */
    state: 'State',
    /** Whether the external system answered. */
    health: 'Health',
    /** A definition. */
    pipeline: {
        label: 'Pipeline',
        term: 'pipeline',
        count: {
            one: 'pipeline',
            many: 'pipelines',
        },
    },
    /** One execution of a pipeline. */
    run: {
        label: 'Run',
        term: 'run',
        count: {
            one: 'run',
            many: 'runs',
        },
    },
    /**
     * A run that has not settled: queued, or claimed and running.
     *
     * The pair already has a name everywhere else in this product -- `ACTIVE_RUN_STATUSES` in the
     * engine, the `dirigent.worker.in_flight` metric, the column `dg pipeline list` heads, the
     * sentence a refused delete answers with -- so no screen coins a second one. There is no
     * `count` pair: the phrase does not inflect, so a number in front of it is the whole of it.
     */
    in_flight: {
        /** Over the front door's feed of them, and on the overview's tile. */
        heading: 'In flight',
        /** A cell that counts them rather than naming one state of the two. */
        counted: (count: string) => `${count} in flight`,
    },
    /** One node of a pipeline. */
    step: {
        label: 'Step',
        term: 'step',
    },
    /** What a step is, out of the catalog. */
    block: {
        label: 'Block',
        heading: 'Blocks',
        term: 'block',
        count: {
            one: 'block',
            many: 'blocks',
        },
    },
    /** A named credential. */
    connection: {
        label: 'Connection',
        heading: 'Connections',
        count: {
            one: 'connection',
            many: 'connections',
        },
    },
    /** A shape a payload is checked against. */
    schema: {
        label: 'Schema',
        count: {
            one: 'schema',
            many: 'schemas',
        },
    },
    /** A shipped document. */
    example: {
        label: 'Example',
        heading: 'Examples',
        count: {
            one: 'example',
            many: 'examples',
        },
    },
    /** What fires a pipeline without a person. */
    trigger: {
        label: 'Trigger',
        heading: 'Triggers',
    },
    /** A clock that fires a pipeline. */
    schedule: {
        label: 'Schedule',
        heading: 'Schedules',
        term: 'schedule',
        count: {
            one: 'schedule',
            many: 'schedules',
        },
    },
    /** An inbound endpoint that fires a pipeline. */
    webhook: {
        label: 'Webhook',
        heading: 'Webhooks',
        term: 'webhook',
        count: {
            one: 'webhook',
            many: 'webhooks',
        },
    },
    /** A step that waits for an external condition. */
    watch: {
        label: 'Watch',
        heading: 'Watches',
        term: 'watch',
        count: {
            one: 'watch',
            many: 'watches',
        },
    },
    /** One time a schedule went off. Not the verb: what the scheduler decided is an outcome. */
    firing: {
        /** The column of what a schedule last did, and the panel's fact for the same moment. */
        last: 'Last firing',
        heading: 'Firings',
        count: {
            one: 'firing',
            many: 'firings',
        },
    },
    /** One try of one step, or of one delivery. */
    attempt: {
        heading: 'Attempts',
    },
    /** An alert rule. A step's readiness rule is the editor's own word, not this one. */
    rule: {
        label: 'Rule',
        heading: 'Rules',
        count: {
            one: 'rule',
            many: 'rules',
        },
    },
    /** One queued alert delivery. */
    notification: {
        label: 'Notification',
        heading: 'Notifications',
        count: {
            one: 'notification',
            many: 'notifications',
        },
    },
    /** A node that claims work. */
    worker: {
        label: 'Worker',
        count: {
            one: 'worker',
            many: 'workers',
        },
    },
    /** A person's record. */
    account: {
        label: 'Account',
        heading: 'Accounts',
        count: {
            one: 'account',
            many: 'accounts',
        },
    },
    /** What an automation signs in with in place of a password. */
    token: {
        heading: 'Tokens',
        count: {
            one: 'token',
            many: 'tokens',
        },
    },
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
    plugin: {
        label: 'Plugin',
        heading: 'Plugins',
    },
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
    version: {
        label: 'Version',
        heading: 'Versions',
        term: 'version',
    },
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
    /** How much a webhook may be posted: the label, and the number wherever it is drawn. */
    rate_limit: {
        label: 'Rate limit',
        value: (count: string) => `${count} a minute`,
    },
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
    window: {
        label: 'Window',
        term: 'window',
    },
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
    environment: {
        label: 'Environment',
        term: 'environment',
    },
    /** Where this instance keeps its records. */
    database: 'Database',
    /** Where this instance keeps its artifacts. */
    storage: 'Storage',
    /** When the thing was made. */
    created: {
        label: 'Created',
        term: 'created',
    },
    /** When a run was taken up. */
    started: {
        label: 'Started',
        term: 'started',
    },
    /** When the thing was last asked. */
    checked: {
        label: 'Checked',
        term: 'checked',
    },
    /** When the thing last happened. */
    last_seen: 'Last seen',
    /** When an account was last let in. */
    last_signed_in: {
        label: 'Last signed in',
        term: 'last signed in',
    },
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
        /** The last check did not pass, as a row's word and as a sentence. */
        failed: {
            word: 'failed',
            sentence: 'failed its last check',
        },
    },
    /**
     * What a worker's row says is wrong with it, keyed by the concern `lib/workers` reads out
     * of its heartbeat. The concern's own name is a discriminator and is never drawn.
     */
    worker: {
        /** `health.worker.silent` in `dirigent_cli.messages` is the same concern, in this word. */
        silent: 'has gone silent',
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

    /**
     * What anything whose read has not landed says, and the only thing it says.
     *
     * Every card, button, pane and cell in this app waiting on an answer reads this one code.
     * Naming what is being read -- the artifacts, the report, the corpus -- adds no fact the
     * surface it is drawn on has not already given, and "from the server" adds none at all,
     * because every read here is from the server.
     */
    reading: 'Reading',

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
    folded_tags: {
        one: (count: string, tags: string) => `${count} more tag: ${tags}`,
        many: (count: string, tags: string) => `${count} more tags: ${tags}`,
    },

    /** The button at the foot of a table that reads the next page. In flight it says `reading`. */
    load_more: (count: string) => `Load ${count} more`,
    /** What a listing's foot states. It says there is more rather than passing a count off as a total. */
    rows_read: (count: string, noun: string) => `${count} ${noun}`,
    rows_read_more: (count: string, noun: string) => `${count} ${noun}, more to load`,

    /** The cadence the screen keeps on its own. The verb beside it is `action.refresh`. */
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
    empty: 'Nothing matches that.',

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
    /**
     * That nothing came back, wherever this app says so.
     *
     * ONE SENTENCE, AND THE FACTS EACH CALLER ADDS AFTER IT. A read, the corner's dot, a download
     * and the password form were four spellings of one silence; the sentence is written once here
     * and a caller that has something further to say joins its own line to it.
     */
    no_answer: {
        /** The heading over a request that never reached a server. */
        title: 'No answer',
        /** The sentence itself. */
        sentence: 'The server did not answer.',
        /** The same fact inside a line that has already named what was being asked. */
        term: 'the server did not answer',
        /** What a read adds: silence may only mean the server is not up yet. */
        may_be_starting: 'It may be starting, or the connection was lost.',
        /** What the password form adds: with no answer, whether the write happened is not known. */
        password_unconfirmed: 'The password change could not be confirmed.',
    },
    /** The heading over a refusal whose body was not a problem document, which is its status. */
    http_status: (status: string) => `HTTP ${status}`,
    /** The sentence under that one. */
    no_problem_document: (status: string) => `The server answered ${status} with no problem document.`,

    /**
     * What a role gate says, wherever one shuts something.
     *
     * The server's own `server.forbidden` says this in the same words, so a control this bundle
     * shut and a request the server refused read alike. It says that this account cannot, and
     * not what another role could: a shut control is not where the permission model is taught.
     */
    shut: 'Not permitted for your role.',
    /** The heading over an admin screen reached by typing its address, which made no request. */
    admin_only: 'Forbidden',

    /** What the password form refuses on its own, before there is anything to ask. */
    password: {
        title: 'Not accepted',
        current_missing: 'Type the password this account signs in with now.',
        too_short: (characters: string) => `A password must be at least ${characters} characters.`,
        unchanged: 'The new password is the one already in use.',
    },

    /** An address this app does not answer, said where it was opened rather than redirected away. */
    nowhere: {
        detail: 'This app does not answer for the address in the browser bar.',
        /** The one fact the status bar states while that screen is open. */
        note: 'no screen at this address',
    },
} as const

/**
 * Every refusal the instance can send, said in this interface's own words.
 *
 * KEYED BY THE SERVER'S CODE, NOT BY WHAT IT SAYS. The path through this table is the dotted code
 * the refusal arrives under -- `server.no_run` is `refused.server.no_run` -- so `lib/refusal`
 * renders a refusal by looking its code up here and never by reading the English the server minted.
 * A code with no entry falls back to the server's `detail`, which is the old behaviour kept for
 * exactly that case.
 *
 * A SENTENCE HERE IS A TEMPLATE, NOT A FUNCTION. Everywhere else in this file a value in a
 * sentence makes it a function, because a caller in this bundle passes the value and the compiler
 * checks it. A refusal's values arrive as a map off the wire, so there is no call to check: the
 * hole is named instead, `{run_id}`, and the name has to be one the server's own template writes.
 * `scripts/check_refusal_labels.py` holds both halves to that.
 *
 * WHAT IS NOT HERE. A code whose whole text is one param -- the server's `{detail}` -- has no
 * words of its own to translate, so the fallback is already the right rendering. A pack's codes
 * are not here either: the instance serves those from `GET /labels`, because this bundle cannot
 * know which packs are installed.
 */
const refused = {
    alert: {
        bad_template: 'The template in {field} is not valid Jinja: {detail}',
        target_has_no_notifier:
            'Connection {code} is of kind {kind}, which no installed notifier delivers through. Installed: {installed}.',
        unknown_connection: 'No connection coded {code}.',
    },
    artifacts: {
        object_missing:
            'Nothing is stored at {uri}. Run {run} (attempt {attempt}) has an artifact row but storage has no object: restore the artifact root from the backup that matches this database, or prune the run.',
    },
    auth: {
        duplicate_email: 'A user with the email {email} already exists.',
        duplicate_user: 'A user named {username} already exists.',
        last_admin: '{username} is the only active admin. Promote another account before changing this one.',
        weak_password: 'A password must be at least {minimum} characters.',
        wrong_password: 'The current password is not correct.',
    },
    document: {
        carried_connections:
            'This document carries its own connections ({named}), which an instance will not store. Create them on the instance and let the document name them under requires.connections.',
        carried_schemas:
            'This document carries its own schemas ({named}), which an instance will not store. Create them on the instance and let the document name them under requires.schemas.',
        no_format: 'The document declares no format. Add format: {format}.',
        step_schema_interpolated:
            '{code} is resolved once the run has started, and a schema is named by its code. A run takes the shapes its document names when it starts, so write the code this step checks against.',
        unsatisfied: 'The document does not satisfy {format}.',
    },
    host: {
        ambiguous_example:
            'Example {code} is carried by {plugins}, so the code alone does not name one of them.',
        unknown_example: 'No example {code} is installed.',
    },
    parameter: {
        invalid: 'Parameter {location} is invalid: {detail}',
        schema_invalid:
            "The pipeline's parameter schema is not itself valid JSON Schema ({problem}). Apply a corrected document to fix it.",
    },
    pipeline: {
        deactivated: 'Pipeline {code} is deactivated.',
        in_use: 'Pipeline {code} has runs still in flight ({runs}) and cannot be deleted. Finish or cancel them first.',
        no_such_version: 'Pipeline {code} has no version {version}.',
        unknown: 'No pipeline coded {code}.',
    },
    run: {
        not_retryable: 'Step {step} is {status}, and only a settled failure can be retried.',
        schema_not_held:
            'No schema coded {code} exists on this instance ({held}), and this pipeline checks against it. Store that shape, or apply a version of the pipeline that does not name it.',
        unknown_schema:
            'This run holds no shape coded {code}. It checks against the shapes its document named when it started ({available}), and takes no others while it runs.',
    },
    schedule: {
        backfill_one_time:
            'Schedule {code} fires once at one instant, so it has no cadence to enumerate. A backfill needs a cron or an interval schedule.',
        backfill_too_many:
            'A backfill creates at most {cap} runs, and {code} over {start} to {end} enumerates {counted}. Narrow the interval.',
        bad_cron: '{expression} is not a cron expression: {detail}',
        bad_moment: '{text} is not a moment. Write one as 2026-06-01T09:00:00Z.',
        duplicate: 'Pipeline {pipeline} already has a schedule coded {code}.',
        exactly_one_clock:
            'A schedule declares exactly one of cron, interval, or at. This one declares {named}.',
        unknown: 'Pipeline {pipeline} has no schedule coded {code}.',
        unknown_timezone: '{name} is not an IANA timezone this host knows. Try UTC or Europe/Oslo.',
    },
    schema: {
        in_use: 'Schema {code} cannot be removed while {pipelines} name it. A pipeline must stop naming it first.',
        invalid: 'This is not a valid JSON Schema{at}: {detail}',
        no_code:
            'This schema names no code. Give one, set $id, or store it from a file whose name is a code.',
    },
    server: {
        bad_credentials: 'Invalid username or password.',
        bad_cursor: '{name}={after} is not a cursor this listing gave out.',
        connection_exists: 'A connection coded {code} exists.',
        connection_referenced: 'Connection {code} is still referenced. Delete what uses it first.',
        /** The same sentence `refusal.shut` says, held to it by `test_shared_words.py`. */
        forbidden: 'Not permitted for your role.',
        idempotency_key_required:
            'An Idempotency-Key header is required, so a retried request creates one attempt.',
        internal: 'The server failed to handle this request. The server log has the detail.',
        no_alert_rule: 'No alert rule coded {code}.',
        no_artifact: 'No artifact {artifact_id}.',
        no_attempt: 'No attempt {attempt_id}.',
        no_block: 'No block {block_id} is installed.',
        no_connection: 'No connection coded {code}.',
        no_icon: 'This bundle carries no icon.',
        no_run: 'No run {run_id}.',
        no_schema: 'No schema coded {code}.',
        no_token: 'No live token named {name}.',
        no_trigger_document: 'No triggers document coded {code}.',
        no_user: 'No user named {username}.',
        no_user_token: 'No live token named {name} for {username}.',
        playground_header_refused:
            'The playground will not set {header} on itself. It sets no header that plants a cookie, opens this origin to another site, or weakens what a browser enforces here.',
        playground_off_instance:
            '{to} is not a path on this instance. The playground redirects only to paths on this instance.',
        playground_unauthenticated:
            'This route wants a credential: the basic pair {username}/{username}, or the documented bearer token. Both are public constants.',
        prune_names_nothing:
            'Keep names no codes, and pruning against an empty set would deactivate every directory pipeline.',
        redacted_secret:
            '{fields} came back as {redacted}, which is what a read shows for a secret that is set, not a secret. Send the real value, or leave the field out to keep what is stored.',
        too_many_logins: 'Too many login attempts. This instance accepts {per_minute} a minute.',
        too_many_tails: 'You already have {maximum} streams open on this server.',
        unauthenticated: 'Authentication required. Present a bearer token or log in.',
        unknown_connection_kind: 'No connection kind {kind} is installed. Known: {known}.',
    },
    validation: {
        extra_forbidden: 'Unknown key{suggestion}.',
    },
    watch: {
        unknown: 'Pipeline {pipeline} has no watch coded {code}.',
    },
    webhook: {
        duplicate: 'Pipeline {pipeline} already has a webhook coded {code}.',
        name_undeclared: '{name} is not a parameter this pipeline declares. Declared: {declared}.',
        path_empty_segment: '{path} is not a payload path: it has an empty segment.',
        unknown: 'Pipeline {pipeline} has no webhook coded {code}.',
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
    /** The term over the host somebody typed to get here. The one beside it is `word.version`. */
    instance: 'instance',
    /** The line above the heading. */
    eyebrow: 'Welcome to dirigent',
    subtitle: 'Enter your credentials to continue.',
    username_placeholder: 'Your username',
    password_placeholder: 'Your password',
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
        /** Nothing has registered with this instance. */
        workers_empty: 'No worker has ever registered with this instance.',
        /** Every worker answered. */
        workers_well: 'Every worker is answering.',
        /** This instance holds no credentials at all. */
        connections_empty: 'This instance holds no connections.',
        /** One credential refused: which one, what its state is called, and what it said. */
        connection_failed: (code: string, said: string, detail: string) => `${code} ${said}${detail}`,
        /** What the external system said, where it said anything. */
        said: (detail: string) => `: ${detail}`,
        unverified: (count: string) => `${count} could not be verified.`,
        never_checked: {
            one: (count: string) => `${count} has never been checked.`,
            many: (count: string) => `${count} have never been checked.`,
        },
        /** Every credential answered. */
        connections_well: 'Every connection answered when it was last checked.',
        schedules_empty: 'Nothing on this instance fires on its own.',
        schedules_across: {
            one: (scheduled: string, pipelines: string) => `Across ${scheduled} of ${pipelines} pipeline.`,
            many: (scheduled: string, pipelines: string) => `Across ${scheduled} of ${pipelines} pipelines.`,
        },
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
        summary: {
            one: (started: string, outcomes: string) =>
                `${started} run started in the last 24 hours, by the hour: ${outcomes}.`,
            many: (started: string, outcomes: string) =>
                `${started} runs started in the last 24 hours, by the hour: ${outcomes}.`,
        },
    },

    /** The panel beside the chart: the workers and the connections as one list. */
    health: {
        hint: 'The workers claiming work, and every connection.',
        /** A worker with nothing to report: what it is, and how much it can take. */
        worker: {
            one: (count: string) => `worker · ${count} slot`,
            many: (count: string) => `worker · ${count} slots`,
        },
        /** The workers half of the foot, drawn only where it is not perfect. The CLI's own
         * `health.worker.never_registered` opens with these same words. */
        no_worker: 'no worker has ever registered',
        workers_healthy: {
            one: (well: string, total: string) => `${well} of ${total} worker healthy`,
            many: (well: string, total: string) => `${well} of ${total} workers healthy`,
        },
        /** Both halves well, on an instance that holds no credentials. */
        every_worker_well: 'Every worker is healthy, and this instance holds no connections.',
        /** Both halves well. */
        all_well: 'Every worker and every connection is healthy.',
    },

    /** The front door's first feed is headed by the noun, in `word.in_flight`. */
    nothing_in_flight: 'Nothing is in flight.',
    /** The runs that want somebody, on both screens. */
    troubled_runs: 'Runs in trouble',
    nothing_troubled: 'Nothing has failed or finished with errors.',
    /** The firings still ahead. */
    next_firings: 'Next firings',
    no_fire_due: 'No firing is due.',

    /** The column headers of the three feeds. What each foot counts is `word`. */
    column: {
        /** When a live run started. */
        since: 'Since',
        /** The step a run died in. */
        failed_at: 'Failed at',
        /** What that step said. */
        error: 'Error',
        /** When the run was last doing anything. */
        when: 'When',
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
    /** How many rows the search left, out of how many were read. */
    shown_of_loaded: (shown: string, loaded: string) => `${shown} of ${loaded}`,
    /** The column header no shared noun covers. */
    column: {
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
    /**
     * What fires a pipeline on its own, which is what the glyphs in the column are titled with.
     *
     * The three kinds are counted in `word`, singular and plural: this holds only the joining.
     */
    trigger_summary: {
        /** The last count, joined to the ones before it. */
        and: (counts: string, last: string) => `${counts} and ${last}`,
        none: 'nothing fires this on its own',
    },
    /** How the newest run of a pipeline reads in the listing. */
    last_run: {
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
        all_tags: (tags: string) => `No pipeline is tagged with all of ${tags}.`,
        /** This instance holds none. */
        none: 'No pipelines.',
    },
    /** The picker over the installed starters. */
    starters: {
        /** Under the title, saying what choosing one does. */
        description: 'Copy a shipped document into the editor, under a code of your own',
        placeholder: 'Search the starters',
        /** What was typed matches no starter. */
        empty: 'No starter matches that.',
        /** Nothing installed here ships one. */
        none: 'No starters installed. Plugins contribute them.',
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
        /** The chip's own tooltip, which is where what makes a version is said. */
        explained: (version: string) =>
            `Version ${version}. Only an apply that changes the document creates a version.`,
    },

    /** The strip above the canvas, and what this screen contributes to the command palette. */
    topbar: {
        /** What the breadcrumb and the palette's shelf call a document nothing has applied yet. */
        new_pipeline: 'new pipeline',
        /** The palette shelf this screen's rows sit on. */
        shelf: (group: string, pipeline: string) => `${group} — ${pipeline}`,
        /** The chip counting what differs from the version the instance holds. */
        unapplied_edits: {
            one: (count: string) => `${count} unapplied edit`,
            many: (count: string) => `${count} unapplied edits`,
        },
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
        /** The menu opened before the catalog landed, which is not a catalog with nothing in it. */
        reading_catalog: 'Reading the catalog…',
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
        /** Under the name box: a name is a display string and the key is what is referenced. */
        name_note: (step: string) => `Display only. Every reference to this step is by its key, ${step}.`,
        /** Above the list of what one field's own schema refuses. */
        refused_at_apply: 'Applying will be refused because of this step.',
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
        attempts: {
            one: (count: string) => `${count} attempt`,
            many: (count: string) => `${count} attempts`,
        },
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
        no_connections: 'This pipeline names no connections.',
        /** A named connection the listing has not landed for, so nothing is claimed about it. */
        health_unread: 'health unread',
        requires_nothing: 'This document requires nothing of an instance.',
        block_chip: (block: string) => `block ${block}`,
        connection_chip: (connection: string) => `connection ${connection}`,
        schema_chip: (schema: string) => `schema ${schema}`,
        pipeline_chip: (pipeline: string) => `pipeline ${pipeline}`,
        missing_chip_title: (thing: string) =>
            `${thing} is not installed on this instance, so applying and running this document will fail`,
        no_triggers:
            'Nothing fires this pipeline on its own. A document declares them under its triggers key.',
        /** Between a watch and the step it watches. */
        watch_on: 'on',
        /** A schedule declaring none of the keys that would say when it fires. */
        no_clock: 'no clock',
        recent_runs: 'Recent runs',
        no_runs: 'No runs.',
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
        /** Why Apply is shut on a document that is already the version the instance holds. */
        nothing_to_apply: 'This document is the version the instance holds.',
        /** What an apply that wrote nothing amounts to, said as a line rather than a dialog. */
        unchanged: (pipeline: string) => `${pipeline} already matches this document. Nothing was written.`,
    },

    /**
     * The way through a refusal made for a section the document carries.
     *
     * The refusal itself is the server's and arrives with its own code; none of these repeat
     * it. They say what this screen does about it: what becomes of each carried entry, why a
     * connection is never one of the things it stores, and what stands in the way.
     */
    carried: {
        /** The section over the list, headed with the word the corpus already uses. */
        title: 'Carried',
        /** Why the button waits, which is the read of what this instance holds. */
        unread: 'What this instance holds has not been read yet.',
        /** The rule and what applying does, in the one line over the list. */
        note: (applying: string) => `An instance does not store what a document carries. ${applying}`,
        stores: {
            one: 'Applying stores the schema marked create, and names every code here under requires.',
            many: 'Applying stores the schemas marked create, and names every code here under requires.',
        },
        names_only: 'Applying names every code here under requires.',
        /** What one carried entry is called on its row, lower case and inside a line. */
        noun: {
            schema: 'schema',
            connection: 'connection',
        },
        /** What becomes of one entry, in the words its row reads. */
        state: {
            /** Stored on this instance from what the document carries. */
            create: 'create',
            /** The instance holds it already, and what it holds is what the document will use. */
            held: 'already here',
            /** The instance holds something else under that code. */
            differs: 'differs',
            /** The instance has not got it, and nothing here stores it. */
            missing: 'missing',
        },
        /** What was stored, once it has been, since the plan after it may write nothing. */
        stored: {
            one: (count: string, codes: string) => `Stored ${count} schema: ${codes}`,
            many: (count: string, codes: string) => `Stored ${count} schemas: ${codes}`,
        },
        /**
         * The row's own control, which opens the form that mints it under that row.
         *
         * The row already carries the code and the kind, so the word on the control is the
         * verb alone and the whole of it is what a reader who cannot see the row hears.
         */
        create_row: (code: string) => `Create connection ${code}`,
        /** The same, for the row whose stored schema would be replaced by what is carried. */
        update_row: (code: string) => `Update schema ${code}`,
        /** The confirm inside that row, which says the whole of what pressing it does. */
        update_confirm: 'Update the stored schema',
        /** Over the pane in that row: which of the two shapes is being read. */
        held_heading: 'On this instance',
        /** What the pane's own window is titled, which is the shape and where it is held. */
        held_body: (code: string) => `${code} · on this instance`,
        /** What updating does, and what it does to everything else naming the code. */
        update_note:
            'Updating replaces what the instance holds with what this document carries. Every pipeline naming this code checks against the new shape from its next run.',
        /**
         * Which pipelines those are, where the instance holds any.
         *
         * The note says a replacement reaches whoever names the code; this says who. The
         * document being applied may not be among them, and that is the point: the reader is
         * deciding for other people's pipelines.
         */
        update_used_by: {
            one: (pipelines: string) => `That is ${pipelines}.`,
            many: (pipelines: string) => `Those are ${pipelines}.`,
        },
        /** Why a credential is never taken out of a document, whatever fields it declares. */
        connection_note:
            'A connection is not created from a document: a document can carry a credential in plain text, in a password field or inside a URL.',
        /** Why applying is shut: a code the document carries is a shape the instance does not hold. */
        differs_why: {
            one: (code: string) =>
                `This instance holds a schema coded ${code} that is not what this document carries. Every pipeline naming that code checks against the stored one from its next run.`,
            many: (codes: string) =>
                `This instance holds schemas coded ${codes} that are not what this document carries. Every pipeline naming those codes checks against the stored ones from its next run.`,
        },
        /** Why the apply would refuse: a connection the document names is not on this instance. */
        no_connection: {
            one: (code: string) => `This instance has no connection coded ${code}.`,
            many: (codes: string) => `This instance has no connections coded ${codes}.`,
        },
        /** Why the apply would refuse for an account that may not store a schema. */
        no_schema_gate: "This document's schemas are not stored, and only an admin can store one.",
        /** What is said when the lift produced nothing a document could be read back from. */
        lift_failed: 'The carried sections could not be taken out of this document. Edit it by hand.',
    },

    /** What the server said an apply would do, as the dialog and the status bar read it. */
    plan: {
        refuse: (pipeline: string) => `Applying ${pipeline} will be refused`,
        unchanged: (pipeline: string) => `Apply writes nothing — ${pipeline} already matches this document`,
        create: (pipeline: string) => `Apply creates ${pipeline} at version 1`,
        update: (version: string, pipeline: string) => `Apply writes version ${version} of ${pipeline}`,
        steps_added: {
            one: (steps: string) => `step added: ${steps}`,
            many: (steps: string) => `steps added: ${steps}`,
        },
        steps_removed: {
            one: (steps: string) => `step removed: ${steps}`,
            many: (steps: string) => `steps removed: ${steps}`,
        },
        steps_changed: {
            one: (steps: string) => `step changed: ${steps}`,
            many: (steps: string) => `steps changed: ${steps}`,
        },
        params_changed: 'the parameter schema changed',
        triggers_changed: 'the triggers changed',
        settings_changed: 'the name, description, or concurrency policy changed',
        /** A plan that would write a version, and change nothing a reader would scan for. */
        no_changes: 'No changes from the stored version.',
        /** What the instance refuses about the document, counted. */
        issues_refuse: {
            one: (count: string) => `${count} issue — applying will be refused`,
            many: (count: string) => `${count} issues — applying will be refused`,
        },
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
        schema: (schema: string) => `the schema ${schema} is not stored on this instance`,
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
    /** The link over the fields a form folds away; the count decides which form is drawn. */
    more_fields: {
        one: (count: string) => `${count} more field`,
        many: (count: string) => `${count} more fields`,
    },
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
        shapes: (label: string, shapes: string) => `${label} must be ${shapes}`,
        one_of: (label: string, options: string) => `${label} must be one of ${options}`,
        boolean: (label: string) => `${label} must be true or false`,
        text: (label: string) => `${label} must be text`,
        number: (label: string) => `${label} must be a number`,
        map: (label: string) => `${label} must be a map, or a reference to one`,
        /** One entry of a map, named by its key. */
        entry: (label: string, key: string, shapes: string) => `${label}.${key} must be ${shapes}`,
        /** The count decides which form is drawn, so the number crosses rather than the text. */
        min_length: {
            one: (label: string, count: string) => `${label} must be at least ${count} character long`,
            many: (label: string, count: string) => `${label} must be at least ${count} characters long`,
        },
        max_length: {
            one: (label: string, count: string) => `${label} must be at most ${count} character long`,
            many: (label: string, count: string) => `${label} must be at most ${count} characters long`,
        },
        pattern: (label: string, pattern: string) => `${label} does not match ${pattern}`,
        whole_number: (label: string) => `${label} must be a whole number`,
        minimum: (label: string, least: string) => `${label} must be at least ${least}`,
        maximum: (label: string, most: string) => `${label} must be at most ${most}`,
        greater_than: (label: string, least: string) => `${label} must be greater than ${least}`,
        less_than: (label: string, most: string) => `${label} must be less than ${most}`,
        /** Text in a JSON box that does not parse, where the engine said nothing itself. */
        not_json: 'that is not JSON',
        /** One cell of a map, holding something the map does not take. */
        map_values: (label: string, shapes: string) => `${label} values must be ${shapes}`,
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
    fresh: {
        one: (count: string) => `${count} new run`,
        many: (count: string) => `${count} new runs`,
    },
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
    clipboard_refused: 'this browser would not write to the clipboard',
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
     * ONLY THIS SCREEN'S OWN. A term naming something the whole product names -- a run, a step,
     * a block, a pipeline, a version, a window, when it was created or started -- is `word`, in
     * that noun's own lower-case `term`, so the column header over it and the term beside it
     * cannot drift apart. What is left here is what nothing else says.
     */
    fact: {
        by: 'by',
        finished: 'finished',
        trace: 'trace',
        /** When this step becomes ready, over the steps it waits for. Not an alert rule. */
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
    node_items: {
        one: (count: string) => `${count} item`,
        many: (count: string) => `${count} items`,
    },
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

    artifacts_empty: 'No step of this run wrote an output.',
    /** What an artifact the run itself wrote is filed under, where a step's is filed under it. */
    artifact_of_run: 'the run',

    // The Report tab.

    report_pending: 'The report is written when this run settles.',
    report_download: 'Download the markdown',
    report_missing:
        'This run rendered no report document. A pipeline document declares one under its report key.',
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
    level_filter: 'Minimum log level',
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
    count: {
        one: (shown: string, total: string) => `${shown} of ${total} line`,
        many: (shown: string, total: string) => `${shown} of ${total} lines`,
    },

    // The lines themselves.

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

    copied: {
        one: (count: string) => `${count} line copied`,
        many: (count: string) => `${count} lines copied`,
    },
    saved: {
        one: (count: string) => `${count} line saved`,
        many: (count: string) => `${count} lines saved`,
    },

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
 * Next, Endpoint, Signature, Rate limit, Step, Cursor, Pinned parameters, Payload mapping, and
 * each kind's own heading and count -- are `word`; the chips a trigger wears are `state.armed`;
 * and the verbs its panel offers are `action`. Only this screen's own words are here.
 */
const triggers = {
    /** No trigger of any kind on the instance. */
    empty: 'Nothing fires on its own. A document declares them under its triggers key.',
    /** The palette row that reads the listing again. */
    reload: 'Read the triggers again',
    /** A trigger the pipeline's own document declares, where no triggers document owns it. */
    managed: 'managed',
    /** The window title over a trigger's pinned parameters. */
    pinned_title: (code: string) => `${code} · pinned parameters`,

    /** The clocks. */
    schedule: {
        /** The header button, the palette row, and the dialog's own title. */
        new: 'New schedule',
        empty: 'No schedules. A document declares one under its triggers key.',
        /** An interval clock, drawn as what it repeats. */
        every: (interval: string) => `every ${interval}`,
        /** A row that arrived with none of the three clock fields filled in. */
        no_clock: 'no clock',
        /** A clock that names no further moment, where the next firing would be. */
        none_due: 'no firing due',
        /** The panel's history, for a schedule that has fired nothing. */
        no_firings: 'No firings.',
        /** What one firing was due for, beside the outcome it had. */
        due: (when: string) => `due ${when}`,
        /**
         * How one firing came out. Keyed by `FiringOutcome` on the wire.
         *
         * The words are the wire's own because the wire's own are the right English; keeping
         * them here is what lets a second language have them at all, and what stopped the
         * schedules table drawing a value nothing in the catalogue had ever seen.
         */
        outcome: {
            fired: 'fired',
            queued: 'queued',
            replaced: 'replaced',
            skipped: 'skipped',
            failed: 'failed',
        },
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
            no_pipeline: 'Choose a pipeline.',
            no_code: 'Enter a code.',
            no_clock: 'Nothing says when this fires.',
            params_refused: 'A pinned parameter is not valid for this pipeline.',
        },
    },

    /** The inbound endpoints. */
    webhook: {
        /** The header button, the palette row, and the dialog's own title. */
        new: 'New webhook',
        empty: 'No webhooks. A document declares one under its triggers key.',
        /** Where a caller posts, as the listing cell and the panel fact both spell it. */
        post: (path: string) => `POST ${path}`,
        /** Whether a delivery is proved to have come from who it says. */
        signed: 'HMAC',
        unsigned: 'unsigned',
        /** When something last arrived: the listing's column and the panel's fact. */
        last_delivery: 'Last delivery',
        /** How one delivery came out. Keyed by `WebhookOutcome` on the wire. */
        outcome: {
            accepted: 'accepted',
            skipped: 'skipped',
            rejected: 'rejected',
        },
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
            /** Said beside Create, because the token is answered once and never again. */
            token_once: 'Its token is shown once, after Create.',
            /** Why Create is shut. */
            no_pipeline: 'Choose a pipeline.',
            no_code: 'Enter a code.',
        },
        /** The one moment a minted token is readable. */
        token: {
            title: (code: string) => `The token for ${code}`,
            note: 'This instance keeps only its hash. This is the only time it can be read; rotating the webhook is how a lost token is replaced.',
            /** Over the path a caller is configured with. */
            url: 'Where to POST',
        },
    },

    /**
     * The sensors. A watch is only ever declared by a document, so there is no dialog and no
     * New: what this block holds is the listing, the panel, and the words a wait is in.
     */
    watch: {
        empty: 'No watches. A document declares one under its triggers key.',
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
        more: 'Load more',
    },

    /** What both new-trigger dialogs say, whichever kind is being declared. */
    dialog: {
        pipeline_hint: 'Search by name or code',
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
        params_not_object: 'The parameters must be a JSON object.',
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

    /** What follows the created instant when the record has been edited since. */
    also_updated: ' · updated ',
    /** Under the name box: what a name is not, and what a reference uses instead. */
    name_hint: (code: string) => `Display only. Every reference to this credential is by its code, ${code}.`,
    description_placeholder: 'What this credential is for. Markdown is rendered.',
    /** The heading over the controls the kind's own schema built. */
    settings_heading: 'Settings',
    /** Why Save or Create is shut. `Refusal` is drawn beside the boxes it is about, so the
     * sentence does not have to say which way to look. */
    settings_refused: 'A setting is not valid for this kind.',

    /** The dialog that mints one, under its title. */
    sealed: 'Secret fields are sealed on the way in and never read back out.',
    /** An example of the shape a code is typed in. */
    code_placeholder: 'playground',
    /** The kind box before anything is chosen. */
    choose_kind: 'Choose a kind',
    /** Why Create is shut, in the order the dialog decides it. */
    needs_code: 'Enter a code.',
    needs_kind: 'Choose a kind.',
    /** Why Create is shut on a kind nothing here publishes a config for. */
    kind_unknown: (kind: string) => `This instance has no connection kind coded ${kind}.`,
    unreadable_setting: 'A setting holds text that is not a value.',

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
    empty: 'No blocks installed. Plugins contribute them.',
    empty_filtered: 'Nothing in the catalog matches that.',

    /** The count of shipped documents that use a block, which links to those documents. */
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
            noun: {
                one: 'scheme',
                many: 'schemes',
            },
        },
        notifier: {
            title: 'Notifiers',
            noun: {
                one: 'notifier',
                many: 'notifiers',
            },
        },
        connection: {
            title: 'Connection kinds',
            noun: {
                one: 'connection kind',
                many: 'connection kinds',
            },
        },
    },
    /** A registry row's title column, which holds an id and the line its schema opens with. */
    entry_header: 'Entry',

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
    none_installed: 'No examples installed. Plugins contribute them.',
    /** The filters left nothing. */
    none_match: 'No example matches that.',
    /** Nothing to show, with nothing being narrowed. */
    empty: 'No examples.',

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
            /** What the registry itself is called, which is not the instance's own `Storage`. */
            storage: 'storage scheme',
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
    requires_nothing: 'This document requires nothing of an instance.',
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
    empty: 'No schemas.',
    /** How many shapes this instance holds, which the screen states under its heading. */
    count: {
        one: (many: string) => `${many} schema`,
        many: (many: string) => `${many} schemas`,
    },
    /** Over the schema body in the panel. */
    body_title: (code: string) => `${code} · schema`,

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
    /** A body the browser could not read as JSON, said where it was typed. */
    unreadable: (error: string) => `The schema is not readable JSON: ${error}`,

    /**
     * Under the name box: that the name is stored beside the schema rather than read out of it.
     *
     * A create reads the schema's own `title`; an update does not, so the two can part company
     * and the box is what decides which one the screen reads. That is semantics the control
     * cannot show, which is the only thing a hint is for.
     */
    name_hint: 'Stored beside the schema. Editing title in the body does not move it.',
    /** The description box, which is the schema's own `description` as it was stored. */
    description_placeholder: 'What this shape is for. Markdown is rendered.',
    /** Why editing the body is a decision rather than a correction, over the names it reaches. */
    body_warning: 'Every pipeline naming this code checks against this shape from its next run.',

    /**
     * What the edit does not reach, under the pipelines it does.
     *
     * It reads after the names rather than before them, because the line above governs that
     * list and a run in flight is not on it. `dg schema update` says the same two
     * facts in the same order, and `test_shared_words.py` holds the pair to one wording.
     */
    body_in_flight: 'A run in flight keeps the shape it started with.',

    /** The section naming the stored pipelines that check against this code. */
    used_by: 'Used by',

    /**
     * The fold over the dependants that did not fit, which draws the rest where it stands.
     *
     * The names are capped rather than drawn to whatever length the instance has, so a shape
     * fifty pipelines name is a section a reader can see past instead of a panel that is mostly
     * one list.
     */
    more_pipelines: {
        one: (count: string) => `${count} more pipeline`,
        many: (count: string) => `${count} more pipelines`,
    },

    /**
     * Why the delete control is shut, worn by the wrapper around it.
     *
     * Removing a shape a stored pipeline names is refused, and a control that cannot act says so
     * before it is pressed rather than after.
     */
    in_use: {
        one: (pipelines: string) => `${pipelines} names this shape, so it cannot be removed.`,
        many: (pipelines: string) => `${pipelines} name this shape, so it cannot be removed.`,
    },
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
    accounts_empty: 'No accounts.',

    /** The panel's line of dates, where the account has never signed in. */
    never_signed_in: 'never signed in',
    /** Under the name field: that the name carries no identity and the username does. */
    name_hint: (username: string) =>
        `Display only. Every reference to this account is by the username it signs in as, ${username}.`,
    /** The placeholder on a field that may be left blank. */
    optional: 'Optional',
    email_hint: 'Unique across accounts.',
    /** What each role may do, in the one line the radio row says under its name. */
    role_hint: {
        admin: 'Everything, including accounts, tokens and connections.',
        operator: 'Define, run and observe pipelines.',
        viewer: 'Read what this instance holds, and change nothing.',
    },
    /** The panel's button, and the title of the dialog it opens. */
    reset_password: 'Reset password',
    /** The button above the tokens listing, in the panel, and the title of the dialog they open. */
    new_token: 'New token',

    /** Under that heading: that a signed-in session is not one of these. */
    tokens_hint: 'A session is never listed here.',
    tokens_empty: 'No tokens.',
    last_used_column: 'Last used',
    /** The accessible name of a row's revoke button, which the row itself does not repeat. */
    revoke_row: (token: string) => `Revoke ${token}`,

    /** Under the new-account dialog's title. */
    new_account_hint: 'The password is what it signs in with the first time.',
    /** Refused in the browser, so a password the server was always going to refuse never leaves it. */
    password_too_short: (minimum: string) => `A password must be at least ${minimum} characters.`,

    /** Under the new-token dialog's title, where the token is the caller's own. */
    token_scope_self: 'This token can do whatever this account can.',
    /** The same line, where the token is minted for another account. */
    token_scope_for: (username: string) => `This token can do whatever ${username} can.`,
    token_name_placeholder: 'ci-deploy',
    token_name_hint: 'Lower case, digits and single hyphens. It is what the token is revoked by.',
    /** Beside the secret, which the server answers once and cannot answer again. */
    token_once: 'This is the only time this token will be shown.',
    copy_token: 'Copy the token',

    /** Under the reset-password dialog's title: what setting a password does to what is open. */
    reset_password_hint: (username: string) =>
        `Resetting signs ${username} out of every session. Its tokens keep working.`,
    new_password: 'New password',
} as const

/**
 * What the worker registry says: the screen, and the table the dashboard draws from the same
 * component. The sentence each of the five concerns says is `state.worker`, not here.
 */
const workers = {
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
        send_test: 'Send a test through a channel',
        reload: 'Read the alert rules again',
    },

    /**
     * The one create this screen offers, on its two surfaces.
     *
     * The button stands under a heading that already says Rules, so it names the rule and no
     * more; the palette row is offered from every screen, and a bare `New rule` there would not
     * say which of this product's two rules it meant.
     */
    new_rule: {
        button: 'New rule',
        palette: 'New alert rule',
    },
    rules_empty: 'No rules.',
    notifications_empty: 'No notifications.',
    /** The same listing, once a filter is what left it empty. */
    notifications_empty_filtered: 'No notification matches these filters.',
    /** The queue's filters, when neither narrows anything. */
    any_status: 'Any status',
    any_notifier: 'Any notifier',
    /** Which sender a message left by, as the queue's filter names it. */
    notifier: 'Notifier',

    /** The strip above the tables: where an alert can go, and whether it still can. */
    channels_heading: 'Channels',
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

    /**
     * What each event is called wherever a rule names one. Keyed by `AlertEvent` on the wire.
     *
     * `dg` prints these same four words from `ALERT_EVENTS` in `dirigent_cli.output`. Neither
     * side can import the other's table and the wire carries codes alone, so the copy stays and
     * `packages/dirigent-cli/tests/test_shared_words.py` fails when the two stop agreeing.
     */
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
    /** The floor a rule fires at, beside the scope rather than in a column of its own. `dg`
     * writes this same half from `IMPORTANCE_FLOOR` in `dirigent_cli.output`. */
    importance_floor: (importance: string) => `${importance} and above`,
    /** What one rule matches, said in one phrase. */
    match_note: (event: string, where: string) => `${event} — ${where}`,
    /** When a rule last delivered anything. */
    last_sent: 'Last sent',
    /** The panel's list of what this rule has sent lately. */
    recent_deliveries: 'Recent deliveries',
    deliveries_empty: 'Nothing sent.',

    /** When the message was put on the queue, which is the row's own `created_at`. */
    queued_at: 'Queued',
    /** When a worker got it through. */
    sent_at: 'Sent',
    /** When a worker will try a message that has not got through yet. */
    next_try: 'Next try',
    /** How many tries there have been, and how many the instance allows, on its two surfaces. */
    attempts_of: {
        /** In a column headed Attempts, where the noun would be the heading said twice. */
        bare: (attempt: number, allowed: number) => `${attempt} of ${allowed}`,
        /** Where nothing above it says what is being counted. */
        counted: {
            one: (attempt: number, allowed: number) => `${attempt} of ${allowed} attempt`,
            many: (attempt: number, allowed: number) => `${attempt} of ${allowed} attempts`,
        },
    },
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
    importance_hint: 'Only pipelines at this importance or above.',
    /** What the control answers with when a rule fires whatever the pipeline is worth. */
    importance_any: 'Any',
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

    /** Why Create is shut on a new rule, in the order somebody fills the form in. */
    unready: {
        code_missing: 'Enter a code.',
        code_shape: 'A code is lowercase letters and digits, joined by single - or _.',
        pipeline_missing: 'Choose a pipeline.',
        throttle_shape: 'A throttle is a duration, such as 15m.',
    },

    /** What sending a test amounts to, under the dialog's title. */
    test_explained: 'The message goes through the same queue a real alert does, and a worker delivers it.',
    /**
     * What a test message says when nobody writes a subject.
     *
     * The dialog draws this as the subject box's placeholder and sends it when the box is left
     * empty, so the placeholder is what the channel will actually receive rather than a guess at
     * the server's own default. `TestRequest.subject` holds the same words for a caller that
     * sends none, and `dirigent-cli/tests/test_shared_words.py` fails when the two drift.
     */
    test_subject: 'dirigent test alert',
    send: 'Send',
    /** The same verb once one message has already gone. */
    send_again: 'Send again',
    /** Show the message the dialog is watching in the queue behind it. */
    open_in_queue: 'Open in the queue',
    /** Where the message got to, as the dialog watches the row settle. */
    delivered: 'Delivered',
    queued_for_worker: 'Queued for the next worker pass.',
    /** Where the delivery ran out of the tries the instance allows. */
    delivery_stopped: {
        one: (attempt: number, allowed: number) => `Delivery stopped after ${attempt} of ${allowed} attempt.`,
        many: (attempt: number, allowed: number) =>
            `Delivery stopped after ${attempt} of ${allowed} attempts.`,
    },
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
    },

    /** The fact a row adds where its control cannot show one. */
    description: {
        timezone: 'Every timestamp on screen. A schedule keeps its own zone.',
        current_line: 'Every editor, including a read-only one and one in a window.',
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
    refused,
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

/** A sentence, or the noun inside one, whose grammar moves with the count it is about. */
export interface Counted<T> {
    one: T
    many: T
}

/**
 * Which form of a counted sentence to draw.
 *
 * The boundary between the two is a fact about the language, so it is decided here once rather
 * than in each of the dozen components that draw one. A language with more than two forms
 * changes this function and the shape of `Counted`, and nothing else.
 */
export function counted<T>(count: number, sentence: Counted<T>): T {
    return count === 1 ? sentence.one : sentence.many
}

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
