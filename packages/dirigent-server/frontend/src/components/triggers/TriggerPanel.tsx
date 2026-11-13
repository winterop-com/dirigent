import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router'

import { CronField } from '@winterop-com/sokkel-ui/CronField'

import { Description } from '@/components/Description'
import { DescriptionList } from '@winterop-com/sokkel-ui/DescriptionList'
import { Instant } from '@/components/Instant'
import { JsonBlock } from '@/components/JsonBlock'
import { PipelineRef } from '@/components/PipelineRef'
import { Refusable } from '@/components/Refusable'
import { sayRefusal } from '@/components/Refusal'
import { EndpointAddress, NewToken } from '@/components/triggers/Endpoint'
import { Chip, Clock, Dot, NextFire, OwnerChip } from '@/components/triggers/marks'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { useFirings } from '@/hooks/use-firings'
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
    inputLine,
    listensTo,
    setSourcePaused,
    stateView,
    type SourceInputOut,
    type SourceOut,
} from '@/lib/sources'
import { CRON_SAVED_WORDS, FIRINGS_READ, firingOf, readCron } from '@/lib/trigger-form'
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

            {schedule.cron !== null && (
                <CronClock cron={schedule.cron} timezone={schedule.timezone} paused={schedule.paused} />
            )}

            <DescriptionList
                termWidth={FACT_TERM}
                items={[
                    ...(schedule.cron === null
                        ? [
                              { term: LABELS.word.clock, value: <Clock schedule={schedule} /> },
                              { term: LABELS.word.timezone, value: schedule.timezone },
                              ...(nextFireView(schedule).kind === 'paused'
                                  ? []
                                  : [{ term: LABELS.word.next, value: <NextFire schedule={schedule} /> }]),
                          ]
                        : []),
                    ...(schedule.last_fired_at === null
                        ? []
                        : [
                              {
                                  term: LABELS.word.firing.last,
                                  value: <Instant at={schedule.last_fired_at} />,
                              },
                          ]),
                    ...(Object.keys(schedule.params).length === 0
                        ? []
                        : [
                              {
                                  term: LABELS.word.pinned_parameters,
                                  value: (
                                      <JsonBlock
                                          title={LABELS.triggers.pinned_title(schedule.code)}
                                          text={asJson(schedule.params)}
                                      />
                                  ),
                              },
                          ]),
                ]}
            />

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
}: {
    source: SourceOut
    pipelineName: string | null
    /** Called with what a verb answered, so the row behind updates without a re-read. */
    onChanged: (row: SourceOut) => void
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

            <DescriptionList
                termWidth={FACT_TERM}
                items={[
                    { term: LABELS.word.kind.label, value: source.kind, code: true },
                    ...(listens === null
                        ? []
                        : [
                              {
                                  term: LABELS.triggers.source.listens,
                                  value:
                                      source.url_path === null ? (
                                          <span className="font-mono">{listens}</span>
                                      ) : (
                                          <EndpointAddress source={source} />
                                      ),
                              },
                          ]),
                    ...(source.next_poll_at === null || paused
                        ? []
                        : [
                              {
                                  term: LABELS.triggers.source.next_poll,
                                  value: <Instant at={source.next_poll_at} />,
                              },
                          ]),
                    ...(source.last_error === null
                        ? []
                        : [
                              {
                                  term: LABELS.triggers.source.last_error,
                                  value: <span className="text-muted-foreground">{source.last_error}</span>,
                              },
                          ]),
                    ...(auth === null ? [] : [{ term: LABELS.triggers.source.auth, value: auth }]),
                    {
                        term: LABELS.word.in_flight.heading,
                        value:
                            source.max_in_flight === null
                                ? String(source.in_flight)
                                : LABELS.triggers.source.bounded(
                                      String(source.in_flight),
                                      String(source.max_in_flight),
                                  ),
                        numeric: true,
                    },
                    ...(source.accepted + source.failed + source.refused > 0
                        ? [
                              {
                                  term: LABELS.triggers.source.taken,
                                  value: (
                                      <span>
                                          {LABELS.triggers.source.accepted(String(source.accepted))}
                                          {source.failed > 0 && (
                                              <span className="text-muted-foreground">
                                                  {' · '}
                                                  {LABELS.triggers.source.failed(String(source.failed))}
                                              </span>
                                          )}
                                          {source.refused > 0 && (
                                              <span className="text-muted-foreground">
                                                  {' · '}
                                                  {LABELS.triggers.source.refused(String(source.refused))}
                                              </span>
                                          )}
                                      </span>
                                  ),
                              },
                          ]
                        : []),
                    {
                        term: LABELS.triggers.source.last_input,
                        value:
                            source.last_input_at === null ? (
                                <span className="text-faint">{LABELS.word.never}</span>
                            ) : (
                                <Instant at={source.last_input_at} />
                            ),
                    },
                ]}
            />

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
                <NewToken source={source} body={undefined} onReplaced={onChanged} />
            </div>

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

/**
 * A saved cron clock: the expression, its reading in words, its zone, and the firings the
 * instance reads back from now. A paused clock is asked nothing and lists no firings, since
 * resuming recomputes them from the moment it resumes.
 */
function CronClock({ cron, timezone, paused }: { cron: string; timezone: string; paused: boolean }) {
    const reading = useFirings(!paused, 'cron', cron, timezone)
    const [from] = useState(() => new Date())
    const runs = useMemo(
        () => (reading.kind === 'firings' ? reading.firings.map((firing) => new Date(firing)) : null),
        [reading],
    )
    return (
        <CronField
            data-testid="schedule-clock"
            readOnly
            paused={paused}
            value={cron}
            onChange={ignore}
            from={from}
            count={FIRINGS_READ}
            timeZone={timezone}
            runs={runs}
            runsPending={reading.kind === 'pending'}
            invalid={reading.kind === 'refused' ? reading.detail : undefined}
            describe={readCron}
            format={firingOf}
            words={CRON_SAVED_WORDS}
        />
    )
}

/** A read-only field's change handler, which nothing calls. */
function ignore(): void {}

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

/** How wide a trigger's fact terms are: the longest, "Pinned parameters", on one line. */
const FACT_TERM = '8rem'

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
                    <Link
                        className="font-mono text-foreground underline-offset-2 hover:underline"
                        to={`/runs/${view.runId}`}
                    >
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
                <Instant className="text-faint" at={input.created_at} />
                {view.runId !== null && (
                    <Link
                        className="font-mono text-foreground underline-offset-2 hover:underline"
                        to={`/runs/${view.runId}`}
                    >
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
