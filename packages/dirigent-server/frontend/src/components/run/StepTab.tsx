import { ChevronRight } from 'lucide-react'
import { useMemo, useState, type CSSProperties } from 'react'

import { Instant } from '@/components/Instant'
import { JsonBlock } from '@/components/JsonBlock'
import { KindChip } from '@/components/KindChip'
import { LogPane } from '@/components/run/LogPane'
import { Fact, Section } from '@/components/run/Panel'
import { StatusChip } from '@/components/run/StatusChip'
import { asJson, countedHeading, elapsedBetween, formatBytes, formatDuration, shortenUri } from '@/lib/format'
import {
    attemptOrder,
    itemLabels,
    itemOutputs,
    logsForStep,
    nodeTone,
    outputReading,
    readsAsTheWholeStep,
    type ItemOutput,
    type RunDetailState,
    type StepView,
} from '@/lib/run-detail'
import type { JsonMap } from '@/lib/api'
import { headingOf } from '@/lib/identity'
import { itemsNote, type AttemptEvent } from '@/lib/runs'
import { runSettled, statusTokens, stepSettled, type AttemptStatus } from '@/lib/status'
import { cn } from '@/lib/utils'

/**
 * One step: where it is, every try it has had, what it was configured with, and what it wrote.
 *
 * THE TRIES OF ONE ELEMENT ARE NEWEST FIRST, AND THE ELEMENTS ARE IN FAN-OUT ORDER. The
 * question in front of somebody opening a step is what happened last, and the try before it is
 * context for that rather than the other way round -- but the elements of a fan-out are the list
 * the step was mapped over, and a list read back to front is no order at all.
 *
 * AN ERROR CLASS IS A CHIP, NOT A PREFIX. `rejected` and `transient` say whether trying again
 * could ever help, which is the first thing somebody reading a failure wants -- and a word
 * glued to the front of the message reads as part of it. `unknown` classifies nothing and is
 * drawn as nothing.
 *
 * THE CONFIG IS THE PIPELINE'S, NOT THE RUN'S, when the run pinned an older version: this API
 * carries a document for a pipeline's current version, so a run of an earlier one is told that
 * rather than shown a config it did not run under.
 */
export function StepTab({
    state,
    view,
    config,
    configVersion,
}: {
    state: RunDetailState
    view: StepView
    /** The step's stanza in the pipeline document, or nothing when there is none to show. */
    config: JsonMap | null
    /** Which pipeline version the config above came from, and which the run pinned. */
    configVersion: { shown: number | null; pinned: number }
}) {
    const entries = logsForStep(state.logs, view.node.code)
    const labels = useMemo(() => itemLabels(state), [state])
    const tries = attemptOrder(view.attempts)
    const started = view.attempts.find((attempt) => attempt.started_at !== null)?.started_at ?? null
    const heading = headingOf(view.node)
    const stale = configVersion.shown !== null && configVersion.shown !== configVersion.pinned
    const done = stepSettled(view.outcome) || runSettled(state.run.status)
    const items = itemsNote(view.node.items_total, view.node.items_failed)
    const queued = spanFact(view.queued_ms, view.duration_ms)
    const waiting = spanFact(view.waiting_ms, view.duration_ms)

    return (
        <div className="flex min-h-0 flex-col gap-4 p-4">
            <div className="space-y-2">
                <div className="flex items-center gap-2">
                    <StatusChip status={nodeTone(view)} />
                    <span className={cn('truncate text-sm font-semibold', !heading.named && 'font-mono')}>
                        {heading.title}
                    </span>
                </div>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    {heading.code !== null && (
                        <Fact term="step" detail={<span className="font-mono">{heading.code}</span>} />
                    )}
                    <Fact term="block" detail={<span className="font-mono">{view.node.block}</span>} />
                    <Fact term="rule" detail={view.node.rule} />
                    {view.node.depends_on.length > 0 && (
                        <Fact term="after" detail={view.node.depends_on.join(', ')} />
                    )}
                    <Fact term="started" detail={<Instant at={started} />} />
                    {/* A step that never queued or never parked says so by saying nothing: a
                        fact reading zero is a row spent on an answer of "no", and one reading
                        the whole of the step is the row above it said again. */}
                    {queued !== null && <Fact term="queued" detail={queued} />}
                    <Fact term="took" detail={formatDuration(view.duration_ms)} />
                    {waiting !== null && <Fact term="waiting" detail={waiting} />}
                    {view.node.fan_out && items !== null && <Fact term="items" detail={items} />}
                </dl>
            </div>

            <Section title={countedHeading('Attempts', view.attempts.length)}>
                {view.attempts.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No attempts.</p>
                ) : (
                    <ul className="space-y-2">
                        {tries.map((attempt) => (
                            <AttemptRow key={attempt.id} attempt={attempt} />
                        ))}
                    </ul>
                )}
            </Section>

            <Section title="Output">
                {view.node.fan_out ? (
                    <FanOutOutput step={view.node.code} attempts={view.attempts} />
                ) : (
                    <StepOutput step={view.node.code} attempts={view.attempts} />
                )}
            </Section>

            <Section title="Config">
                {stale && (
                    <p className="text-xs text-muted-foreground">
                        This run pinned version {configVersion.pinned}; the config below is version{' '}
                        {String(configVersion.shown)}, which is what the pipeline holds now.
                    </p>
                )}
                {config === null ? (
                    <p className="text-xs text-muted-foreground">
                        The pipeline document names no config for this step.
                    </p>
                ) : (
                    <JsonBlock title={`${view.node.code} · config`} text={asJson(config)} />
                )}
            </Section>

            <Section title="Log">
                <LogPane entries={entries} items={labels} settled={done} className="max-h-72 min-h-24" />
            </Section>
        </div>
    )
}

/** One of a step's spans, or nothing where it says nothing the row above it does not. */
function spanFact(span: number | null, whole: number | null): string | null {
    if (span === null || span === 0 || readsAsTheWholeStep(span, whole)) return null
    return formatDuration(span)
}

/**
 * What the step produced, which is what the next step's reference reads.
 *
 * The newest attempt that produced anything speaks for the step: an output small enough to
 * inline is shown whole, one that went to storage is named by where it went, and a step that
 * has produced nothing says so instead of showing an empty box.
 */
function StepOutput({ step, attempts }: { step: string; attempts: readonly AttemptEvent[] }) {
    const produced = attempts
        .toReversed()
        .find((attempt) => attempt.output !== null || attempt.output_uri !== null)
    if (produced === undefined) {
        return <p className="text-xs text-muted-foreground">No output.</p>
    }
    const reading = outputReading(produced)
    if (reading.uri !== null) {
        return <StoredOutput uri={reading.uri} bytes={reading.bytes} />
    }
    return <JsonBlock title={`${step} · output`} text={asJson(reading.value)} className="max-h-72" />
}

/** An output that went to storage, said as where it went and how large it is there. */
function StoredOutput({ uri, bytes, className }: { uri: string; bytes: number | null; className?: string }) {
    return (
        <p className={cn('font-mono text-xs text-faint', className)} title={uri}>
            {shortenUri(uri)} ({formatBytes(bytes)})
        </p>
    )
}

/**
 * What a fan-out step produced, which is one output per element rather than one for the step.
 *
 * A FAN-OUT STEP'S OUTPUT IS THE LIST OF ITS ELEMENTS' OUTPUTS, in item order, and only the
 * elements that succeeded are in it -- so the step after it reads a short list rather than one
 * with a hole. Drawing the newest element's output under the heading "Output" would say the step
 * produced that one value, which is not what the next step's reference reads.
 *
 * EACH ELEMENT IS FOLDED. A fan-out of sixty is sixty outputs, and the question is usually which
 * elements are in the list at all; the value itself is one click under the label it is keyed by.
 */
function FanOutOutput({ step, attempts }: { step: string; attempts: readonly AttemptEvent[] }) {
    const items = itemOutputs(attempts)
    if (items.length === 0) {
        return <p className="text-xs text-muted-foreground">No items.</p>
    }
    return (
        <>
            <p className="text-xs text-muted-foreground">
                The step after this one reads these as one list, in item order. An item that did not succeed
                is not in the list.
            </p>
            <ul>
                {items.map((item) => (
                    <ItemOutputRow key={item.id} step={step} item={item} />
                ))}
            </ul>
        </>
    )
}

/** Why an element is not in the step's list, said as the state that kept it out. */
function absenceNote(status: AttemptStatus): string {
    if (status === 'failed') return 'failed, so it is not in the list'
    if (status === 'cancelled') return 'cancelled, so it is not in the list'
    if (status === 'skipped') return 'skipped, so it is not in the list'
    return 'no output'
}

/** One element's output, keyed by the label the element is known by and folded until asked for. */
function ItemOutputRow({ step, item }: { step: string; item: ItemOutput }) {
    const [open, setOpen] = useState(false)
    const produced = item.produced
    const reading = produced === null ? null : outputReading(produced)
    if (produced === null || reading === null) {
        return (
            <li className="flex items-baseline gap-2 py-1">
                <span className="font-mono text-xs">{item.key}</span>
                <span className="text-xs text-muted-foreground">{absenceNote(item.status)}</span>
            </li>
        )
    }
    return (
        <li>
            <button
                type="button"
                aria-expanded={open}
                onClick={() => {
                    setOpen(!open)
                }}
                className="row-hover flex w-full items-center gap-2 rounded-sm py-1 text-left"
            >
                <ChevronRight className={cn('size-3 shrink-0', open && 'rotate-90')} aria-hidden />
                <span className="truncate font-mono text-xs">{item.key}</span>
                {reading.bytes !== null && (
                    <span className="ml-auto shrink-0 text-xs text-faint">{formatBytes(reading.bytes)}</span>
                )}
            </button>
            {open &&
                (reading.uri !== null ? (
                    <StoredOutput uri={reading.uri} bytes={reading.bytes} className="pl-5" />
                ) : (
                    <JsonBlock
                        title={`${step} · ${item.key} · output`}
                        text={asJson(reading.value)}
                        className="max-h-72"
                    />
                ))}
        </li>
    )
}

/** The class worth naming, or nothing: `unknown` is what the engine says when it cannot say. */
function classOf(attempt: AttemptEvent): string | null {
    const named = attempt.error_class
    return named === null || named === 'unknown' ? null : named
}

/** One try, on a rail in its own state's hue. */
function AttemptRow({ attempt }: { attempt: AttemptEvent }) {
    const classified = classOf(attempt)
    return (
        <li
            className="status-rail row-hover rounded-r-sm"
            style={statusTokens(attempt.status) as CSSProperties}
        >
            <div className="flex items-center gap-2">
                <StatusChip status={attempt.status} />
                <span className="text-xs text-muted-foreground">
                    attempt {attempt.attempt}
                    {attempt.kind === 'manual' && ', asked for'}
                </span>
                <span className="ml-auto text-xs text-faint">
                    {formatDuration(elapsedBetween(attempt.started_at, attempt.finished_at))}
                </span>
            </div>
            {attempt.item !== null && (
                <p className="font-mono text-xs text-muted-foreground">item {attempt.item}</p>
            )}
            {attempt.waiting_message !== null && (
                <p className="text-xs text-muted-foreground">{attempt.waiting_message}</p>
            )}
            {attempt.error !== null && (
                /* The failure is the sentence this row exists for, so it gets a block of its
                   own rather than a red aside squeezed against the chips. */
                <div className="mt-1 rounded-sm bg-critical/10 px-2 py-1.5">
                    {classified !== null && <KindChip kind={classified} className="mb-1" />}
                    <p className="font-mono text-xs break-words text-critical">{attempt.error}</p>
                </div>
            )}
            {attempt.output_uri !== null && (
                <p className="font-mono text-xs text-faint" title={attempt.output_uri}>
                    {shortenUri(attempt.output_uri)} ({formatBytes(attempt.output_bytes)})
                </p>
            )}
        </li>
    )
}
