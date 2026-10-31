import { useCallback, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { Description } from '@/components/Description'
import { JsonBlock } from '@/components/JsonBlock'
import { PipelineRef } from '@/components/PipelineRef'
import { Refusable } from '@/components/Refusable'
import { sayRefusal } from '@/components/Refusal'
import { Chip, Clock, Dot, NextFire, OwnerChip } from '@/components/triggers/marks'
import { Button } from '@/components/ui/button'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { asJson, formatInstant, formatRelative, shortId } from '@/lib/format'
import { headingOf, type Addressable } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import {
    authLine,
    inputId,
    inputView,
    isPaused,
    readSourceInputs,
    rotatable,
    rotateSourceToken,
    inputLine,
    listensTo,
    setSourcePaused,
    stateView,
    type SourceInputOut,
    type SourceOut,
    type SourceTokenOut,
} from '@/lib/sources'
import {
    firingView,
    nextFireView,
    readFirings,
    setSchedulePaused,
    type FiringOut,
    type ScheduleOut,
} from '@/lib/triggers'

/**
 * One trigger beside the listing: what it is, and what it has actually done.
 *
 * THE HISTORY IS A CURSOR WALK LIKE ANY OTHER. Firings and inputs page by an integer
 * cursor, newest first, so the panel reads one page and asks for the next when somebody wants
 * it -- the same `usePaged` the listings use, and for the same reason: there is no total to
 * state and no page to jump to.
 *
 * WHAT IS EDITABLE HERE IS WHAT DOES NOT LIVE IN THE DOCUMENT. Whether a schedule or a source
 * is paused is operational state the instance owns, so it is a verb here even on a managed
 * trigger; the clock came from a document and changes by applying one.
 */
export function SchedulePanel({
    pipeline,
    pipelineName,
    schedule,
    onChanged,
}: {
    pipeline: string
    pipelineName: string | null
    schedule: ScheduleOut
    /** Called with what a verb answered, so the row behind updates without a re-read. */
    onChanged: (row: ScheduleOut) => void
}) {
    const [busy, setBusy] = useState(false)

    const read = useCallback(
        (after: string | null) => readFirings(pipeline, schedule.code, after),
        [pipeline, schedule.code],
    )
    const { state, more } = usePaged(read, firingId)

    const write = useMayWrite()

    const toggle = () => {
        setBusy(true)
        void setSchedulePaused(pipeline, schedule.code, !schedule.paused)
            .then(onChanged, sayRefusal)
            .finally(() => {
                setBusy(false)
            })
    }

    return (
        <div className="space-y-4 p-4">
            <Head
                thing={schedule}
                pipeline={pipeline}
                pipelineName={pipelineName}
                description={schedule.description}
            >
                <OwnerChip managed={schedule.managed} document={schedule.trigger_document} />
                {schedule.paused && <Chip>{LABELS.state.armed.paused}</Chip>}
            </Head>

            <dl className="space-y-1.5">
                <Fact label={LABELS.word.clock}>
                    <Clock schedule={schedule} />
                </Fact>
                <Fact label={LABELS.word.timezone}>{schedule.timezone}</Fact>
                {nextFireView(schedule).kind !== 'paused' && (
                    <Fact label={LABELS.word.next}>
                        <NextFire schedule={schedule} />
                    </Fact>
                )}
                {schedule.last_fired_at !== null && (
                    <Fact label={LABELS.word.firing.last}>
                        <span title={formatInstant(schedule.last_fired_at)}>
                            {formatRelative(schedule.last_fired_at)}
                        </span>
                    </Fact>
                )}
                {Object.keys(schedule.params).length > 0 && (
                    <Fact label={LABELS.word.pinned_parameters}>
                        <div className="mt-1">
                            <JsonBlock
                                title={LABELS.triggers.pinned_title(schedule.code)}
                                text={asJson(schedule.params)}
                            />
                        </div>
                    </Fact>
                )}
            </dl>

            <Refusable why={write.why}>
                <Button
                    variant="outline"
                    size="sm"
                    disabled={busy || !write.may}
                    title={write.why}
                    onClick={toggle}
                >
                    {schedule.paused ? LABELS.action.resume : LABELS.action.pause}
                </Button>
            </Refusable>

            <History
                title={LABELS.word.firing.heading}
                empty={LABELS.triggers.schedule.no_firings}
                loading={!state.read}
                rows={state.rows}
                keyOf={firingId}
                next={state.next}
                reading={state.reading}
                onMore={more}
                render={(firing) => <Firing firing={firing} />}
            />
        </div>
    )
}

export function SourcePanel({
    source,
    pipelineName,
    onChanged,
    onMinted,
}: {
    source: SourceOut
    pipelineName: string | null
    /** Called with what a verb answered, so the row behind updates without a re-read. */
    onChanged: (row: SourceOut) => void
    /** Called with a token that is readable exactly once, which the screen shows and forgets. */
    onMinted: (token: SourceTokenOut) => void
}) {
    const [busy, setBusy] = useState(false)

    const read = useCallback(
        (after: string | null) => readSourceInputs(source.pipeline, source.code, after),
        [source.pipeline, source.code],
    )
    const { state, more } = usePaged(read, inputId)

    const write = useMayWrite()
    const view = stateView(source)
    const listens = listensTo(source)
    const auth = authLine(source)
    const paused = isPaused(source)

    function act<T>(work: Promise<T>, taken: (answer: T) => void): void {
        setBusy(true)
        void work.then(taken, sayRefusal).finally(() => {
            setBusy(false)
        })
    }

    return (
        <div className="space-y-4 p-4">
            <Head
                thing={source}
                pipeline={source.pipeline}
                pipelineName={pipelineName}
                description={source.description}
            >
                <span className="flex items-center gap-1.5 text-xs">
                    <Dot tone={view.tone} />
                    {view.label}
                </span>
            </Head>

            <dl className="space-y-1.5">
                <Fact label={LABELS.word.kind.label}>
                    <span className="font-mono">{source.kind}</span>
                </Fact>
                {listens !== null && (
                    <Fact label={LABELS.triggers.source.listens}>
                        <span className="font-mono break-all">{listens}</span>
                    </Fact>
                )}
                {source.next_poll_at !== null && !paused && (
                    <Fact label={LABELS.triggers.source.next_poll}>
                        <span title={formatInstant(source.next_poll_at)}>
                            {formatRelative(source.next_poll_at)}
                        </span>
                    </Fact>
                )}
                {source.last_error !== null && (
                    <Fact label={LABELS.triggers.source.last_error}>
                        <span className="break-words text-muted-foreground">{source.last_error}</span>
                    </Fact>
                )}
                {auth !== null && (
                    <Fact label={LABELS.triggers.source.auth}>
                        <span className="font-mono">{auth}</span>
                    </Fact>
                )}
                <Fact label={LABELS.word.in_flight.heading}>
                    <span>
                        {source.max_in_flight === null
                            ? String(source.in_flight)
                            : LABELS.triggers.source.bounded(
                                  String(source.in_flight),
                                  String(source.max_in_flight),
                              )}
                    </span>
                </Fact>
                {source.accepted + source.refused > 0 && (
                    <Fact label={LABELS.triggers.source.taken}>
                        <span>
                            {LABELS.triggers.source.accepted(String(source.accepted))}
                            {source.refused > 0 && (
                                <span className="text-muted-foreground">
                                    {' · '}
                                    {LABELS.triggers.source.refused(String(source.refused))}
                                </span>
                            )}
                        </span>
                    </Fact>
                )}
                <Fact label={LABELS.triggers.source.last_input}>
                    {source.last_input_at === null ? (
                        <span className="text-faint">{LABELS.word.never}</span>
                    ) : (
                        <span title={formatInstant(source.last_input_at)}>
                            {formatRelative(source.last_input_at)}
                        </span>
                    )}
                </Fact>
            </dl>

            <div className="flex flex-wrap items-center gap-2">
                <Refusable why={write.why}>
                    <Button
                        variant="outline"
                        size="sm"
                        disabled={busy || !write.may}
                        title={write.why}
                        onClick={() => {
                            act(setSourcePaused(source.pipeline, source.code, !paused), onChanged)
                        }}
                    >
                        {paused ? LABELS.action.resume : LABELS.action.pause}
                    </Button>
                </Refusable>
                {rotatable(source) && (
                    <Refusable why={write.why}>
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={busy || !write.may}
                            title={write.why}
                            onClick={() => {
                                act(rotateSourceToken(source.pipeline, source.code), (token) => {
                                    onMinted(token)
                                    onChanged({
                                        ...source,
                                        token_prefix: token.prefix,
                                        secret_fingerprint: token.fingerprint,
                                    })
                                })
                            }}
                        >
                            {source.auth === 'hmac'
                                ? LABELS.triggers.source.rotate_secret
                                : LABELS.triggers.rotate}
                        </Button>
                    </Refusable>
                )}
            </div>
            {rotatable(source) && <p className="text-xs text-faint">{LABELS.triggers.rotate_warning}</p>}

            <History
                title={LABELS.triggers.source.inputs}
                empty={LABELS.triggers.source.nothing_received}
                loading={!state.read}
                rows={state.rows}
                keyOf={inputId}
                next={state.next}
                reading={state.reading}
                onMore={more}
                render={(input) => <Received input={input} />}
            />
        </div>
    )
}

const firingId = (row: FiringOut) => String(row.id)

/** One trigger's title over its code, the pipeline it fires, and whatever it is wearing. */
function Head({
    thing,
    pipeline,
    pipelineName,
    description,
    children,
}: {
    thing: Addressable
    pipeline: string
    pipelineName: string | null
    description: string | null
    children: ReactNode
}) {
    const heading = headingOf(thing)
    return (
        <div className="space-y-1">
            <p className="flex flex-wrap items-center gap-2">
                <span className={heading.named ? 'text-sm font-semibold' : 'font-mono text-sm font-semibold'}>
                    {heading.title}
                </span>
                {children}
                {heading.code !== null && (
                    <span className="font-mono text-xs text-muted-foreground">{heading.code}</span>
                )}
            </p>
            <PipelineRef code={pipeline} name={pipelineName} inline />
            <Description text={description} />
        </div>
    )
}

/** One fact, on the line under its label. */
function Fact({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className="flex flex-wrap items-baseline gap-2">
            <dt className="w-32 shrink-0 text-xs text-muted-foreground">{label}</dt>
            <dd className="min-w-0 text-sm">{children}</dd>
        </div>
    )
}

/** A trigger's own history, one page at a time, newest first. */
function History<T>({
    title,
    empty,
    loading,
    rows,
    keyOf,
    next,
    reading,
    onMore,
    render,
}: {
    title: string
    empty: string
    loading: boolean
    rows: readonly T[]
    keyOf: (row: T) => string
    next: string | null
    reading: boolean
    onMore: () => void
    render: (row: T) => ReactNode
}) {
    return (
        <div className="space-y-2">
            <p className="text-xs text-muted-foreground">{title}</p>
            {loading && <p className="text-xs text-faint">{LABELS.shell.reading}</p>}
            {!loading && rows.length === 0 && <p className="text-xs text-faint">{empty}</p>}
            <ul className="divide-y divide-border">
                {rows.map((row) => (
                    <li key={keyOf(row)} className="row-hover -mx-4 px-4 py-2">
                        {render(row)}
                    </li>
                ))}
            </ul>
            {next !== null && (
                <Button
                    variant="ghost"
                    size="sm"
                    className="w-full text-muted-foreground"
                    disabled={reading}
                    onClick={onMore}
                >
                    {reading ? LABELS.shell.reading : LABELS.triggers.history.more}
                </Button>
            )}
        </div>
    )
}

/** One firing: when it was due, what came of it, and the run it started. */
function Firing({ firing }: { firing: FiringOut }) {
    const view = firingView(firing)
    return (
        <div className="space-y-0.5">
            <span className="flex items-center gap-2 text-xs">
                <Dot tone={view.tone} />
                <span>{view.label}</span>
                <span className="text-faint" title={formatInstant(firing.scheduled_for)}>
                    {LABELS.triggers.schedule.due(formatRelative(firing.scheduled_for))}
                </span>
                {view.runId !== null && (
                    <Link className="font-mono text-foreground underline-offset-2 hover:underline" to={`/runs/${view.runId}`}>
                        {shortId(view.runId)}
                    </Link>
                )}
            </span>
            {view.detail !== null && (
                <p className="text-xs break-words text-muted-foreground">{view.detail}</p>
            )}
        </div>
    )
}

/** One input: what came of it, the status its caller was answered, and the run or the reason. */
function Received({ input }: { input: SourceInputOut }) {
    const view = inputView(input)
    const line = inputLine(input)
    return (
        <div className="space-y-0.5">
            <span className="flex items-center gap-2 text-xs">
                <Dot tone={view.tone} />
                <span>{view.label}</span>
                {input.status !== null && (
                    <span className="font-mono text-muted-foreground">{input.status}</span>
                )}
                <span className="text-faint" title={formatInstant(input.created_at)}>
                    {formatRelative(input.created_at)}
                </span>
                {view.runId !== null && (
                    <Link className="font-mono text-foreground underline-offset-2 hover:underline" to={`/runs/${view.runId}`}>
                        {shortId(view.runId)}
                    </Link>
                )}
            </span>
            {line !== null && (
                <p className="truncate font-mono text-xs text-faint" title={line}>
                    {line}
                </p>
            )}
            {input.reason !== null && (
                <p className="text-xs break-words text-muted-foreground">{input.reason}</p>
            )}
        </div>
    )
}
