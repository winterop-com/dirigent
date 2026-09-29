import { REPORTS_DOCS_URL } from '@/lib/docs'
import { LABELS } from '@/lib/labels'

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
        title: LABELS.reference.jq.paths.title,
        entries: [
            { form: '.a.b', says: LABELS.reference.jq.paths.nested },
            { form: '.[0]  .[-1]', says: LABELS.reference.jq.paths.ends },
            { form: '.[]', says: LABELS.reference.jq.paths.each },
            { form: '.a?', says: LABELS.reference.jq.paths.optional },
            { form: '.. | .id?', says: LABELS.reference.jq.paths.descend },
        ],
    },
    {
        title: LABELS.reference.jq.shape.title,
        entries: [
            { form: '{code: .id, name}', says: LABELS.reference.jq.shape.object },
            { form: '[.[] | .value]', says: LABELS.reference.jq.shape.list },
            { form: '. + {seen: true}', says: LABELS.reference.jq.shape.added_field },
            { form: 'to_entries  from_entries', says: LABELS.reference.jq.shape.entries },
        ],
    },
    {
        title: LABELS.reference.jq.filter.title,
        entries: [
            { form: 'map(f)  select(cond)', says: LABELS.reference.jq.filter.map },
            { form: 'add  length  min  max', says: LABELS.reference.jq.filter.aggregate },
            { form: 'group_by(.k)  sort_by(.k)', says: LABELS.reference.jq.filter.group },
            { form: 'unique_by(.k)  min_by(.k)', says: LABELS.reference.jq.filter.unique },
            { form: 'reduce .[] as $x (0; . + $x)', says: LABELS.reference.jq.filter.reduce },
        ],
    },
    {
        title: LABELS.reference.jq.strings.title,
        entries: [
            { form: 'ascii_downcase  ltrimstr("x")', says: LABELS.reference.jq.strings.case },
            { form: 'split(",")  join(",")', says: LABELS.reference.jq.strings.split },
            { form: 'tostring  tonumber', says: LABELS.reference.jq.strings.convert },
            { form: '@csv  @tsv  @base64', says: LABELS.reference.jq.strings.encode },
            { form: 'now | todate', says: LABELS.reference.jq.strings.now },
            { form: 'strptime("%Y-%m-%d") | mktime', says: LABELS.reference.jq.strings.parse_date },
        ],
    },
    {
        title: LABELS.reference.jq.missing.title,
        entries: [
            { form: '.a // "default"', says: LABELS.reference.jq.missing.alternative },
            { form: 'has("a")  in(.)', says: LABELS.reference.jq.missing.has_key },
            { form: 'if . == null then empty else . end', says: LABELS.reference.jq.missing.drop_null },
        ],
    },
    {
        title: LABELS.reference.jq.runtime.title,
        entries: [
            { form: '. as $rows | ...', says: LABELS.reference.jq.runtime.bind_input },
            { form: 'env  $ENV', says: LABELS.reference.jq.runtime.environment },
            { form: 'input  inputs', says: LABELS.reference.jq.runtime.inputs },
        ],
    },
]

const SQL: Group[] = [
    {
        title: LABELS.reference.sql.runtime.title,
        entries: [
            {
                form: 'select ... where day = :day',
                says: LABELS.reference.sql.runtime.bound_value,
            },
            {
                form: 'one statement',
                says: LABELS.reference.sql.runtime.statements,
            },
            { form: 'max_rows', says: LABELS.reference.sql.runtime.max_rows },
        ],
    },
]

const SHELL: Group[] = [
    {
        title: LABELS.reference.shell.runtime.title,
        entries: [
            { form: 'argv: [cmd, arg]', says: LABELS.reference.shell.runtime.argv },
            { form: 'command: "a | b"', says: LABELS.reference.shell.runtime.command },
            { form: 'env  env_allowlist', says: LABELS.reference.shell.runtime.environment },
            { form: 'cwd', says: LABELS.reference.shell.runtime.cwd },
        ],
    },
]

const JINJA: Group[] = [
    {
        title: LABELS.reference.jinja.facts.title,
        entries: [
            { form: 'run.status  run.params.x', says: LABELS.reference.jinja.facts.run },
            { form: 'pipeline.name  pipeline.code', says: LABELS.reference.jinja.facts.pipeline },
            { form: 'step.name.output.value', says: LABELS.reference.jinja.facts.step },
            { form: 'steps  items  items_failed', says: LABELS.reference.jinja.facts.steps },
            { form: 'rendered_at  url', says: LABELS.reference.jinja.facts.rendered },
        ],
    },
    {
        title: LABELS.reference.jinja.filters.title,
        entries: [
            { form: '{{ s.duration_ms | duration }}', says: LABELS.reference.jinja.filters.duration },
            { form: '{{ s.output_bytes | bytes }}', says: LABELS.reference.jinja.filters.bytes },
            { form: '{{ run.started_at | iso }}', says: LABELS.reference.jinja.filters.iso },
            {
                form: '{{ x | round(1) }}  {{ xs | join(", ") }}',
                says: LABELS.reference.jinja.filters.builtin,
            },
        ],
    },
    {
        title: LABELS.reference.jinja.control.title,
        entries: [
            { form: '{% for name, s in step.items() %}', says: LABELS.reference.jinja.control.loop },
            { form: '{% if step.keep.output %}', says: LABELS.reference.jinja.control.conditional },
            { form: '{{ missing }}', says: LABELS.reference.jinja.control.missing },
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
        title: LABELS.reference.jq.title,
        groups: JQ,
        manual: { label: LABELS.reference.jq.manual, href: 'https://jqlang.org/manual/' },
    },
    'application/sql': { title: LABELS.reference.sql.title, groups: SQL, manual: null },
    'text/x-shellscript': { title: LABELS.reference.shell.title, groups: SHELL, manual: null },
    'text/x-jinja': {
        title: LABELS.reference.jinja.title,
        groups: JINJA,
        manual: { label: LABELS.reference.jinja.manual, href: REPORTS_DOCS_URL },
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
                {LABELS.reference.heading(reference.title)}
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
