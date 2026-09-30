import { useCallback, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { Description } from '@/components/Description'
import { JsonBlock } from '@/components/JsonBlock'
import { PipelineRef } from '@/components/PipelineRef'
import { Refusable } from '@/components/Refusable'
import { sayRefusal } from '@/components/Refusal'
import { Chip, Clock, Dot, NextFire, OwnerChip, WatchState } from '@/components/triggers/marks'
import { Button } from '@/components/ui/button'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { asJson, formatInstant, formatRelative, shortId } from '@/lib/format'
import { headingOf, type Addressable } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import {
    deliveryView,
    firingView,
    hookPath,
    nextFireView,
    readDeliveries,
    readFirings,
    rotateWebhookToken,
    setSchedulePaused,
    setWatchPaused,
    setWebhookActive,
    signing,
    watchView,
    type DeliveryOut,
    type FiringOut,
    type ScheduleOut,
    type WatchOut,
    type WebhookOut,
    type WebhookTokenOut,
} from '@/lib/triggers'

/**
 * One trigger beside the listing: what it is, and what it has actually done.
 *
 * THE HISTORY IS A CURSOR WALK LIKE ANY OTHER. Firings and deliveries page by an integer
 * cursor, newest first, so the panel reads one page and asks for the next when somebody wants
 * it -- the same `usePaged` the listings use, and for the same reason: there is no total to
 * state and no page to jump to.
 *
 * WHAT IS EDITABLE HERE IS WHAT DOES NOT LIVE IN THE DOCUMENT. Whether a schedule or a watch is
 * paused and whether a webhook accepts deliveries are operational state the instance owns, so
 * each is a verb here even on a managed trigger; the clock, the mapping and the watched step
 * came from a document and change by applying one.
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

export function WebhookPanel({
    pipeline,
    pipelineName,
    webhook,
    onChanged,
    onMinted,
}: {
    pipeline: string
    pipelineName: string | null
    webhook: WebhookOut
    onChanged: (row: WebhookOut) => void
    /** Called with a token that is readable exactly once, which the screen shows and forgets. */
    onMinted: (token: WebhookTokenOut) => void
}) {
    const [busy, setBusy] = useState(false)

    const read = useCallback(
        (after: string | null) => readDeliveries(pipeline, webhook.code, after),
        [pipeline, webhook.code],
    )
    const { state, more } = usePaged(read, deliveryId)

    const write = useMayWrite()

    /** Carry out one verb, leaving the row as it was and saying so if the server would not. */
    function act<T>(work: Promise<T>, taken: (answer: T) => void): void {
        setBusy(true)
        void work.then(taken, sayRefusal).finally(() => {
            setBusy(false)
        })
    }

    return (
        <div className="space-y-4 p-4">
            <Head
                thing={webhook}
                pipeline={pipeline}
                pipelineName={pipelineName}
                description={webhook.description}
            >
                <OwnerChip managed={webhook.managed} document={webhook.trigger_document} />
                {!webhook.active && <Chip>{LABELS.state.armed.disabled}</Chip>}
            </Head>

            <dl className="space-y-1.5">
                <Fact label={LABELS.word.endpoint}>
                    <span className="font-mono">{LABELS.triggers.webhook.post(hookPath(webhook))}</span>
                </Fact>
                <Fact label={LABELS.word.signature}>{signing(webhook)}</Fact>
                <Fact label={LABELS.word.rate_limit.label}>
                    {LABELS.word.rate_limit.value(String(webhook.rate_limit_per_minute))}
                </Fact>
                <Fact label={LABELS.triggers.webhook.last_delivery}>
                    {webhook.last_delivery_at === null ? (
                        <span className="text-faint">{LABELS.word.never}</span>
                    ) : (
                        <span title={formatInstant(webhook.last_delivery_at)}>
                            {formatRelative(webhook.last_delivery_at)}
                        </span>
                    )}
                </Fact>
                {Object.keys(webhook.params_from_payload).length > 0 && (
                    <Fact label={LABELS.word.payload_mapping}>
                        <div className="mt-1">
                            <JsonBlock
                                title={LABELS.triggers.webhook.mapping_title(webhook.code)}
                                text={asJson(webhook.params_from_payload)}
                            />
                        </div>
                    </Fact>
                )}
            </dl>

            <div className="flex flex-wrap items-center gap-2">
                <Refusable why={write.why}>
                    <Button
                        variant="outline"
                        size="sm"
                        disabled={busy || !write.may}
                        title={write.why}
                        onClick={() => {
                            act(setWebhookActive(pipeline, webhook.code, !webhook.active), onChanged)
                        }}
                    >
                        {webhook.active ? LABELS.action.disable : LABELS.action.enable}
                    </Button>
                </Refusable>
                <Refusable why={write.why}>
                    <Button
                        variant="outline"
                        size="sm"
                        disabled={busy || !write.may}
                        title={write.why}
                        onClick={() => {
                            act(rotateWebhookToken(pipeline, webhook.code), onMinted)
                        }}
                    >
                        {LABELS.triggers.webhook.rotate}
                    </Button>
                </Refusable>
            </div>
            <p className="text-xs text-faint">{LABELS.triggers.webhook.rotate_warning}</p>

            <History
                title={LABELS.triggers.webhook.deliveries}
                empty={LABELS.triggers.webhook.nothing_delivered}
                loading={!state.read}
                rows={state.rows}
                keyOf={deliveryId}
                next={state.next}
                reading={state.reading}
                onMore={more}
                render={(delivery) => <Delivery delivery={delivery} />}
            />
        </div>
    )
}

export function WatchPanel({
    pipeline,
    pipelineName,
    watch,
    onChanged,
}: {
    pipeline: string
    pipelineName: string | null
    watch: WatchOut
    /** Called with what a verb answered, so the row behind updates without a re-read. */
    onChanged: (row: WatchOut) => void
}) {
    const [busy, setBusy] = useState(false)
    const write = useMayWrite()

    const toggle = () => {
        setBusy(true)
        void setWatchPaused(pipeline, watch.code, !watch.paused)
            .then(onChanged, sayRefusal)
            .finally(() => {
                setBusy(false)
            })
    }

    return (
        <div className="space-y-4 p-4">
            <Head
                thing={watch}
                pipeline={pipeline}
                pipelineName={pipelineName}
                description={watch.description}
            >
                <OwnerChip managed={watch.managed} document={watch.trigger_document} />
                {watch.paused && <Chip>{LABELS.state.armed.paused}</Chip>}
            </Head>

            <dl className="space-y-1.5">
                <Fact label={LABELS.word.step.label}>
                    <span className="font-mono">{watch.step}</span>
                </Fact>
                {watchView(watch).kind !== 'paused' && (
                    <Fact label={LABELS.triggers.watch.waiting}>
                        <WatchState watch={watch} />
                    </Fact>
                )}
                {watch.failures > 0 && (
                    <Fact label={LABELS.triggers.watch.failures}>{String(watch.failures)}</Fact>
                )}
                {watch.last_error !== null && (
                    <Fact label={LABELS.triggers.watch.last_error}>
                        <span className="break-words text-critical">{watch.last_error}</span>
                        {watch.last_error_at !== null && (
                            <span
                                className="ml-2 text-xs text-faint"
                                title={formatInstant(watch.last_error_at)}
                            >
                                {formatRelative(watch.last_error_at)}
                            </span>
                        )}
                    </Fact>
                )}
                {watch.cursor !== null && (
                    <Fact label={LABELS.word.cursor}>
                        <div className="mt-1">
                            <JsonBlock
                                title={LABELS.triggers.watch.cursor_title(watch.code)}
                                text={asJson(watch.cursor)}
                            />
                        </div>
                    </Fact>
                )}
                {Object.keys(watch.params).length > 0 && (
                    <Fact label={LABELS.word.pinned_parameters}>
                        <div className="mt-1">
                            <JsonBlock
                                title={LABELS.triggers.pinned_title(watch.code)}
                                text={asJson(watch.params)}
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
                    {watch.paused ? LABELS.action.resume : LABELS.action.pause}
                </Button>
            </Refusable>
        </div>
    )
}

const firingId = (row: FiringOut) => String(row.id)
const deliveryId = (row: DeliveryOut) => String(row.id)

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
                    <Link className="font-mono text-primary-ink hover:underline" to={`/runs/${view.runId}`}>
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

/** One delivery: what it was made of, and the run it started or the reason it started none. */
function Delivery({ delivery }: { delivery: DeliveryOut }) {
    const view = deliveryView(delivery)
    return (
        <div className="space-y-0.5">
            <span className="flex items-center gap-2 text-xs">
                <Dot tone={view.tone} />
                <span>{view.label}</span>
                <span className="text-faint" title={formatInstant(delivery.created_at)}>
                    {formatRelative(delivery.created_at)}
                </span>
                {view.runId !== null && (
                    <Link className="font-mono text-primary-ink hover:underline" to={`/runs/${view.runId}`}>
                        {shortId(view.runId)}
                    </Link>
                )}
                {delivery.source !== null && (
                    <span className="truncate text-faint">
                        {LABELS.triggers.webhook.from(delivery.source)}
                    </span>
                )}
            </span>
            {view.reason !== null && (
                <p className="text-xs break-words text-muted-foreground">{view.reason}</p>
            )}
        </div>
    )
}
