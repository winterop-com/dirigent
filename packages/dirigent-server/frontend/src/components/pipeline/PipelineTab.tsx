import { Link } from 'react-router'

import { Description } from '@/components/Description'
import { Instant } from '@/components/Instant'
import { Fact, Section } from '@/components/run/Panel'
import { StatusChip } from '@/components/run/StatusChip'
import { TagChip } from '@/components/TagChip'
import type { JsonMap } from '@/lib/api'
import { shortDigest } from '@/lib/format'
import { headingOf } from '@/lib/identity'
import type { ConnectionOut } from '@/lib/connections'
import type { PipelineOut, PipelineVersionOut } from '@/lib/pipelines'
import {
    blockMissing,
    connectionMissing,
    connectionsNamed,
    requiredBlocks,
    requiredPipelines,
    type Unmet,
} from '@/lib/requirements'
import type { RunOut } from '@/lib/runs'
import { fieldsOf, type FieldDescriptor } from '@/lib/schema-form'

/**
 * The pipeline as a whole: what it is, what it takes, what it reaches, and what it has done.
 *
 * WHAT IS DRAWN IS THE LOCAL DOCUMENT, not the stored one, wherever the two can differ -- the
 * parameters, the connections it names, the triggers it declares -- because this is the pane
 * beside an editor. What only the instance knows -- the version row, the recent runs, whether a
 * connection answers -- comes from the instance and says so.
 *
 * THE TAGS ARE READ, NEVER EDITED HERE. A document owns them the way it owns its name, so the
 * source is where they are changed and an apply is what changes them.
 *
 * IT IS HANDED WHAT IT DRAWS. The editor reads the document it is editing and the listing reads
 * the stored one for the row somebody chose, so this takes a listing row, a document, and the
 * three readings the instance answers with, and reads nothing itself.
 *
 * WHAT THIS INSTANCE HAS NOT GOT IS SAID WHERE IT STANDS. A required block the catalog does not
 * publish is a critical chip in the Requires row rather than a line somewhere else, and a named
 * connection nobody has configured says so on its own row: the reader is looking at the list of
 * things this document needs, and that is where the news about them belongs.
 */
export function PipelineTab({
    pipeline,
    document,
    versions,
    connections,
    runs,
    unmet,
}: {
    pipeline: PipelineOut
    /** The document this is a pane beside, which is what the parameters and triggers are read from. */
    document: JsonMap | null
    versions: PipelineVersionOut[]
    /** Every connection this instance holds, or null when the listing could not be read. */
    connections: ConnectionOut[] | null
    runs: RunOut[]
    /** What this instance has not got of what the document names. */
    unmet: Unmet
}) {
    const heading = headingOf(pipeline)
    const digest = versions[0]?.digest ?? null
    const parameters = fieldsOf(mapAt(document, 'params'))
    const named = connectionsNamed(document)
    const triggers = mapAt(document, 'triggers')
    const schedules = mapsIn(triggers, 'schedules')
    const webhooks = mapsIn(triggers, 'webhooks')

    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="flex flex-wrap items-center gap-2">
                <h2 className={heading.named ? 'text-sm font-semibold' : 'font-mono text-sm font-semibold'}>
                    {heading.title}
                </h2>
                <span
                    className={
                        pipeline.active
                            ? 'border-good text-good rounded-sm border px-1.5 py-0.5 text-xs'
                            : 'border-border text-muted-foreground rounded-sm border border-dashed px-1.5 py-0.5 text-xs'
                    }
                >
                    {pipeline.active ? 'active' : 'deactivated'}
                </span>
                <span className="text-faint font-mono text-xs">
                    {pipeline.current_version === null ? 'no version' : `v${String(pipeline.current_version)}`}
                </span>
                {heading.code !== null && (
                    <span className="text-muted-foreground font-mono text-xs">{heading.code}</span>
                )}
                {digest !== null && (
                    <span className="text-faint font-mono text-xs" title={digest}>
                        {shortDigest(digest)}
                    </span>
                )}
            </div>
            {pipeline.tags.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    {pipeline.tags.map((tag) => (
                        <TagChip key={tag} tag={tag} />
                    ))}
                </div>
            )}
            {pipeline.description === null ? (
                <p className="text-muted-foreground text-sm">This pipeline carries no description.</p>
            ) : (
                <Description text={pipeline.description} />
            )}

            <Section title="Parameters">
                {parameters.length === 0 ? (
                    <p className="text-muted-foreground text-xs">This pipeline takes no parameters.</p>
                ) : (
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                        {parameters.map((field) => (
                            <Fact
                                key={field.name}
                                term={field.name}
                                detail={
                                    <span className="text-muted-foreground">
                                        {[field.kind, rangeOf(field), defaultOf(field)]
                                            .filter((part) => part !== null)
                                            .join(' · ')}
                                    </span>
                                }
                            />
                        ))}
                    </dl>
                )}
            </Section>

            <Section title="Connections">
                {named.length === 0 ? (
                    <p className="text-muted-foreground text-xs">This pipeline names no connections.</p>
                ) : (
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                        {named.map((name) => {
                            const held = connections?.find((one) => one.code === name) ?? null
                            return (
                                <Fact
                                    key={name}
                                    term={name}
                                    detail={
                                        held === null ? (
                                            <span className={connectionMissing(unmet, name) ? 'text-critical' : 'text-warning'}>
                                                {connectionMissing(unmet, name) ? 'not configured' : 'health unread'}
                                            </span>
                                        ) : (
                                            <span className="text-muted-foreground">
                                                {held.kind} · {healthOf(held)}
                                            </span>
                                        )
                                    }
                                />
                            )
                        })}
                    </dl>
                )}
            </Section>

            <Section title="Requires">
                <div className="flex flex-wrap gap-1.5">
                    {requiredChips(document, unmet).map((chip) => (
                        <span
                            key={chip.label}
                            className={
                                chip.met
                                    ? 'border-border rounded-sm border px-1.5 py-0.5 font-mono text-xs'
                                    : 'border-critical text-critical rounded-sm border px-1.5 py-0.5 font-mono text-xs'
                            }
                            title={
                                chip.met
                                    ? undefined
                                    : `${chip.name} is not installed on this instance, so applying and running this document will fail`
                            }
                        >
                            {chip.label}
                        </span>
                    ))}
                    {requiredChips(document, unmet).length === 0 && (
                        <span className="text-muted-foreground text-xs">
                            This document requires nothing in particular of an instance.
                        </span>
                    )}
                </div>
            </Section>

            <Section title="Triggers">
                {schedules.length === 0 && webhooks.length === 0 ? (
                    <p className="text-muted-foreground text-xs">
                        Nothing fires this pipeline on its own. A document declares them under its triggers key.
                    </p>
                ) : (
                    <ul className="text-muted-foreground space-y-0.5 text-xs">
                        {schedules.map((schedule, index) => (
                            <li key={`schedule-${String(index)}`}>
                                schedule <span className="font-mono">{stringAt(schedule, 'code') ?? '--'}</span>{' '}
                                {clockOf(schedule)}
                            </li>
                        ))}
                        {webhooks.map((webhook, index) => (
                            <li key={`webhook-${String(index)}`}>
                                webhook <span className="font-mono">{stringAt(webhook, 'code') ?? '--'}</span>
                            </li>
                        ))}
                    </ul>
                )}
            </Section>

            <Section title="Recent runs">
                {runs.length === 0 ? (
                    <p className="text-muted-foreground text-xs">No runs.</p>
                ) : (
                    <ul className="space-y-1">
                        {runs.map((run) => (
                            <li key={run.id}>
                                <Link
                                    className="row-hover -mx-4 flex items-center gap-2 px-4 py-0.5 text-xs"
                                    to={`/runs/${run.id}`}
                                >
                                    <StatusChip status={run.status} />
                                    <Instant className="text-faint" at={run.created_at} />
                                </Link>
                            </li>
                        ))}
                    </ul>
                )}
            </Section>

            <Section title="Versions">
                {versions.length === 0 ? (
                    <p className="text-muted-foreground text-xs">No versions.</p>
                ) : (
                    <ul className="space-y-1">
                        {versions.map((version) => (
                            <li
                                key={version.id}
                                className="row-hover -mx-4 flex flex-wrap items-baseline gap-2 px-4 py-0.5 text-xs"
                            >
                                <span className="font-mono">v{version.version}</span>
                                <span className="text-muted-foreground">{version.provenance_source}</span>
                                <span className="text-faint">{version.applied_by ?? 'not recorded'}</span>
                                <Instant className="text-faint" at={version.created_at} />
                            </li>
                        ))}
                    </ul>
                )}
            </Section>
        </div>
    )
}

/** A parameter's bounds, in the one phrase there is room for. */
function rangeOf(field: FieldDescriptor): string | null {
    const { minimum, maximum, minLength, maxLength } = field.bounds
    if (minimum !== undefined || maximum !== undefined) {
        return `${minimum === undefined ? '' : String(minimum)}..${maximum === undefined ? '' : String(maximum)}`
    }
    if (minLength !== undefined || maxLength !== undefined) {
        return `${minLength === undefined ? '0' : String(minLength)}..${maxLength === undefined ? '' : String(maxLength)} chars`
    }
    if (field.options.length > 0) return field.options.map((option) => option.label).join('|')
    return null
}

function defaultOf(field: FieldDescriptor): string | null {
    return field.fallback === undefined ? null : `default ${String(field.fallback)}`
}

/** How a connection's last check reads. */
function healthOf(connection: ConnectionOut): string {
    if (connection.last_check_healthy === null) return 'never checked'
    return connection.last_check_healthy ? 'answering' : (connection.last_check_detail ?? 'not answering')
}

/** One chip under "requires": what is needed, and whether this instance has it. */
interface RequiredChip {
    /** The thing itself, which is what a title names when it is missing. */
    name: string
    label: string
    met: boolean
}

/**
 * The chips under "requires", each said as the kind of thing it is.
 *
 * A block the catalog does not publish is drawn critical, because that is the one this instance
 * can answer for and the one an apply will refuse. A connection is checked against the listing
 * the screen already read; a required pipeline is nobody's to check here, so it is drawn plain.
 */
function requiredChips(document: JsonMap | null, unmet: Unmet): RequiredChip[] {
    return [
        ...requiredBlocks(document).map((name) => ({
            name,
            label: `block ${name}`,
            met: !blockMissing(unmet, name),
        })),
        ...listAt(mapAt(document, 'requires'), 'connections')
            .flatMap((one) => (typeof one === 'string' ? [one] : []))
            .map((name) => ({ name, label: `connection ${name}`, met: !connectionMissing(unmet, name) })),
        ...requiredPipelines(document).map((name) => ({ name, label: `pipeline ${name}`, met: true })),
    ]
}

/** Which clock a schedule declares, in the words the document writes it in. */
function clockOf(schedule: JsonMap): string {
    for (const key of ['cron', 'interval', 'at'] as const) {
        const value = schedule[key]
        if (value !== null && value !== undefined) return `${key} ${String(value)}`
    }
    return 'no clock'
}

function mapAt(value: JsonMap | null, key: string): JsonMap | null {
    const found = value?.[key]
    if (found === null || found === undefined || typeof found !== 'object' || Array.isArray(found)) return null
    return found as JsonMap
}

function listAt(value: JsonMap | null, key: string): unknown[] {
    const found = value?.[key]
    return Array.isArray(found) ? (found as unknown[]) : []
}

/** The mappings in one list, which is what a triggers section holds. */
function mapsIn(value: JsonMap | null, key: string): JsonMap[] {
    return listAt(value, key).flatMap((one) =>
        one !== null && typeof one === 'object' && !Array.isArray(one) ? [one as JsonMap] : [],
    )
}

function stringAt(value: JsonMap, key: string): string | null {
    const found = value[key]
    return typeof found === 'string' ? found : null
}
