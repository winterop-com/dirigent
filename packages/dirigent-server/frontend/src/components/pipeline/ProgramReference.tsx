import { REPORTS_DOCS_URL } from '@/lib/docs'

/**
 * What a program's language offers, beside the window it is written in.
 *
 * A REFERENCE IS THE IDIOMS, NOT THE MANUAL. A jq program is written by somebody who knows what
 * they want the shape to be and reaches for the one filter they cannot remember; a screen of
 * the forms that recur in this corpus answers that, and the manual is one link away for the
 * rest. Each language gets the same treatment, and a media type this app has no reference for
 * gets nothing rather than a placeholder.
 *
 * THE FACTS ARE DIRIGENT'S, NOT THE LANGUAGE'S. What `env` reads, how a value gets bound into
 * a statement, what a template may read: these are this runtime's rules, so they are stated
 * here where the program is written rather than left to the block's docs page.
 */

interface Entry {
    form: string
    says: string
}

interface Group {
    title: string
    entries: Entry[]
}

const JQ: Group[] = [
    {
        title: 'Paths',
        entries: [
            { form: '.a.b', says: 'a field of a field' },
            { form: '.[0]  .[-1]', says: 'first and last of a list' },
            { form: '.[]', says: 'each element in turn' },
            { form: '.a?', says: 'null instead of an error when it is not there' },
            { form: '.. | .id?', says: 'every id, anywhere in the value' },
        ],
    },
    {
        title: 'Shape',
        entries: [
            { form: '{code: .id, name}', says: 'an object from picked fields' },
            { form: '[.[] | .value]', says: 'a list from each element' },
            { form: '. + {seen: true}', says: 'an object with one more field' },
            { form: 'to_entries  from_entries', says: 'an object as {key, value} pairs and back' },
        ],
    },
    {
        title: 'Filter and reduce',
        entries: [
            { form: 'map(f)  select(cond)', says: 'apply to each; keep the ones that match' },
            { form: 'add  length  min  max', says: 'sum, count, extremes' },
            { form: 'group_by(.k)  sort_by(.k)', says: 'lists by a key' },
            { form: 'unique_by(.k)  min_by(.k)', says: 'one per key; the smallest by key' },
            { form: 'reduce .[] as $x (0; . + $x)', says: 'a fold, with the state as .' },
        ],
    },
    {
        title: 'Strings and dates',
        entries: [
            { form: 'ascii_downcase  ltrimstr("x")', says: 'case and trimming' },
            { form: 'split(",")  join(",")', says: 'a string as a list and back' },
            { form: 'tostring  tonumber', says: 'across the string boundary' },
            { form: '@csv  @tsv  @base64', says: 'a list encoded for another program' },
            { form: 'now | todate', says: 'the moment as ISO 8601' },
            { form: 'strptime("%Y-%m-%d") | mktime', says: 'a date string as seconds' },
        ],
    },
    {
        title: 'Missing values',
        entries: [
            { form: '.a // "default"', says: 'the right side when the left is null or false' },
            { form: 'has("a")  in(.)', says: 'whether a key is there' },
            { form: 'if . == null then empty else . end', says: 'drop a null from a stream' },
        ],
    },
    {
        title: 'In this runtime',
        entries: [
            { form: '. as $rows | ...', says: 'the input, bound for the rest of the program' },
            { form: 'env  $ENV', says: 'an empty object here: the worker keeps its environment' },
            { form: 'input  inputs', says: 'not available: the whole input is .' },
        ],
    },
]

const SQL: Group[] = [
    {
        title: 'In this runtime',
        entries: [
            {
                form: 'select ... where day = :day',
                says: 'a value bound by name from params, never interpolated',
            },
            {
                form: 'one statement',
                says: 'sql.query runs one; sql.execute runs several as one transaction',
            },
            { form: 'max_rows', says: 'the cap on what the output carries' },
        ],
    },
]

const SHELL: Group[] = [
    {
        title: 'In this runtime',
        entries: [
            { form: 'argv: [cmd, arg]', says: 'no shell: each argument as written' },
            { form: 'command: "a | b"', says: '/bin/sh -c, for a pipe or a redirect' },
            { form: 'env  env_allowlist', says: 'variables set here, and the worker variables let through' },
            { form: 'cwd', says: 'relative to the run’s work directory, never absolute' },
        ],
    },
]

const JINJA: Group[] = [
    {
        title: 'The facts',
        entries: [
            { form: 'run.status  run.params.x', says: 'the run and what it was started with' },
            { form: 'pipeline.name  pipeline.code', says: 'what ran' },
            { form: 'step.name.output.value', says: 'one step by name, its last output' },
            { form: 'steps  items  items_failed', says: 'every step in order; the fan-out items' },
            { form: 'rendered_at  url', says: 'when this page was written, and the run’s address' },
        ],
    },
    {
        title: 'Filters',
        entries: [
            { form: '{{ s.duration_ms | duration }}', says: '1s34ms' },
            { form: '{{ s.output_bytes | bytes }}', says: '1.2KB' },
            { form: '{{ run.started_at | iso }}', says: 'ISO 8601' },
            { form: '{{ x | round(1) }}  {{ xs | join(", ") }}', says: 'Jinja’s own' },
        ],
    },
    {
        title: 'Control',
        entries: [
            { form: '{% for name, s in step.items() %}', says: 'a table row per step' },
            { form: '{% if step.keep.output %}', says: 'a section only when a step ran' },
            { form: '{{ missing }}', says: 'renders as nothing, never an error' },
        ],
    },
]

interface Reference {
    title: string
    groups: Group[]
    manual: { label: string; href: string } | null
}

const REFERENCES: Record<string, Reference> = {
    'application/jq': {
        title: 'jq',
        groups: JQ,
        manual: { label: 'The jq manual', href: 'https://jqlang.org/manual/' },
    },
    'application/sql': { title: 'SQL', groups: SQL, manual: null },
    'text/x-shellscript': { title: 'shell', groups: SHELL, manual: null },
    'text/x-jinja': {
        title: 'Jinja',
        groups: JINJA,
        manual: { label: 'What a template may read', href: REPORTS_DOCS_URL },
    },
}

/** The reference for a media type, or null when this app has none for it. */
export function referenceFor(mediaType: string | null | undefined): Reference | null {
    return mediaType === undefined || mediaType === null ? null : (REFERENCES[mediaType] ?? null)
}

export function ProgramReference({ mediaType }: { mediaType: string | null | undefined }) {
    const reference = referenceFor(mediaType)
    if (reference === null) return null
    return (
        <div className="flex flex-col gap-4 text-sm">
            <p className="text-xs tracking-wide text-muted-foreground uppercase">
                {reference.title} reference
            </p>
            {reference.groups.map((group) => (
                <section key={group.title} className="flex flex-col gap-1.5">
                    <h3 className="text-xs font-medium text-foreground">{group.title}</h3>
                    <dl className="flex flex-col gap-1.5">
                        {group.entries.map((entry) => (
                            <div key={entry.form} className="flex flex-col">
                                <dt className="font-mono text-xs text-foreground">{entry.form}</dt>
                                <dd className="text-xs text-muted-foreground">{entry.says}</dd>
                            </div>
                        ))}
                    </dl>
                </section>
            ))}
            {reference.manual !== null && (
                <a
                    href={reference.manual.href}
                    target="_blank"
                    rel="noopener"
                    className="text-xs text-primary-ink underline-offset-2 hover:underline"
                >
                    {reference.manual.label}
                </a>
            )}
        </div>
    )
}
