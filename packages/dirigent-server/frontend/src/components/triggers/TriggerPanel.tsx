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
                {schedule.paused && <Chip>paused</Chip>}
            </Head>

            <dl className="space-y-1.5">
                <Fact label="Clock">
                    <Clock schedule={schedule} />
                </Fact>
                <Fact label="Timezone">{schedule.timezone}</Fact>
                {nextFireView(schedule).kind !== 'paused' && (
                    <Fact label="Next">
                        <NextFire schedule={schedule} />
                    </Fact>
                )}
                {schedule.last_fired_at !== null && (
                    <Fact label="Last fired">
                        <span title={formatInstant(schedule.last_fired_at)}>
                            {formatRelative(schedule.last_fired_at)}
                        </span>
                    </Fact>
                )}
                {Object.keys(schedule.params).length > 0 && (
                    <Fact label="Pinned parameters">
                        <div className="mt-1">
                            <JsonBlock
                                title={`${schedule.code} · pinned parameters`}
                                text={asJson(schedule.params)}
                                className="max-h-64"
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
                    {schedule.paused ? 'Resume' : 'Pause'}
                </Button>
            </Refusable>

            <History
                title="Firings"
                empty="Not fired."
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
                {!webhook.active && <Chip>disabled</Chip>}
            </Head>

            <dl className="space-y-1.5">
                <Fact label="Endpoint">
                    <span className="font-mono">POST {hookPath(webhook)}</span>
                </Fact>
                <Fact label="Signature">{signing(webhook)}</Fact>
                <Fact label="Rate limit">{String(webhook.rate_limit_per_minute)} a minute</Fact>
                <Fact label="Last delivery">
                    {webhook.last_delivery_at === null ? (
                        <span className="text-faint">never</span>
                    ) : (
                        <span title={formatInstant(webhook.last_delivery_at)}>
                            {formatRelative(webhook.last_delivery_at)}
                        </span>
                    )}
                </Fact>
                {Object.keys(webhook.params_from_payload).length > 0 && (
                    <Fact label="Payload mapping">
                        <div className="mt-1">
                            <JsonBlock
                                title={`${webhook.code} · payload mapping`}
                                text={asJson(webhook.params_from_payload)}
                                className="max-h-64"
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
                        {webhook.active ? 'Disable' : 'Enable'}
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
                        Rotate token
                    </Button>
                </Refusable>
            </div>
            <p className="text-xs text-faint">
                Rotating creates a new token and forgets the old one immediately. Every caller has to be
                updated.
            </p>

            <History
                title="Deliveries"
                empty="Nothing delivered."
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
                {watch.paused && <Chip>paused</Chip>}
            </Head>

            <dl className="space-y-1.5">
                <Fact label="Step">
                    <span className="font-mono">{watch.step}</span>
                </Fact>
                {watchView(watch).kind !== 'paused' && (
                    <Fact label="Waiting">
                        <WatchState watch={watch} />
                    </Fact>
                )}
                {watch.failures > 0 && <Fact label="Failures in a row">{String(watch.failures)}</Fact>}
                {watch.last_error !== null && (
                    <Fact label="Last error">
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
                    <Fact label="Cursor">
                        <div className="mt-1">
                            <JsonBlock
                                title={`${watch.code} · cursor`}
                                text={asJson(watch.cursor)}
                                className="max-h-64"
                            />
                        </div>
                    </Fact>
                )}
                {Object.keys(watch.params).length > 0 && (
                    <Fact label="Pinned parameters">
                        <div className="mt-1">
                            <JsonBlock
                                title={`${watch.code} · pinned parameters`}
                                text={asJson(watch.params)}
                                className="max-h-64"
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
                    {watch.paused ? 'Resume' : 'Pause'}
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
            {loading && <p className="text-xs text-faint">Reading from the server</p>}
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
                    {reading ? 'Reading' : 'Load more'}
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
                    due {formatRelative(firing.scheduled_for)}
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
                    <span className="truncate text-faint">from {delivery.source}</span>
                )}
            </span>
            {view.reason !== null && (
                <p className="text-xs break-words text-muted-foreground">{view.reason}</p>
            )}
        </div>
    )
}
