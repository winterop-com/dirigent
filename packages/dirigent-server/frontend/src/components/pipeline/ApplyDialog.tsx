import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { CarriedOffer } from '@/components/pipeline/CarriedOffer'
import { PlanReading } from '@/components/pipeline/PlanReading'
import { Refusable } from '@/components/Refusable'
import { Refusal } from '@/components/Refusal'
import { Button } from '@/components/ui/button'
import { useMayWrite } from '@/hooks/use-may-write'
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { type JsonMap, type Problem } from '@/lib/api'
import {
    carriedCodes,
    carriedItems,
    carriedRefusal,
    creations,
    NOTHING_READ,
    offerBlocked,
    offerNote,
    storedNote,
    type Held,
} from '@/lib/carried'
import { readConnection } from '@/lib/connections'
import { LABELS } from '@/lib/labels'
import { local, refusalOf } from '@/lib/refusal'
import { planView, unchangedNote, type PlanView } from '@/lib/pipeline-plan'
import { applyPipeline, type ApplyResult, type PipelinePlan } from '@/lib/pipelines'
import { firstShut } from '@/lib/roles'
import { createSchema, readSchema } from '@/lib/schemas'

/**
 * What applying would do, before anything is written.
 *
 * ONE VERB, ASKED TWICE. `POST /pipelines/$apply?dry_run=true` is the plan and the same call
 * without the flag is the apply, so what this dialog shows and what the button then does are the
 * same request. There is no separate plan endpoint to drift from the real one.
 *
 * VALIDATE IS THIS DIALOG WITHOUT THE BUTTON. The question "would this be refused" and the
 * question "what would applying do" have one answer, and a reader who only wanted the first
 * should not have to be shown a button that writes.
 *
 * A CARRIED SECTION IS THE ONE REFUSAL THIS DIALOG ANSWERS. An instance stores no connection and
 * no schema a document carries, and that refusal stands; what stood beside it was a Cancel and
 * an Apply that would never work, and the remedy it named was a command line. So the refusal
 * keeps its words and the way forward is under it: every carried entry named, the schemas among
 * them stored under the codes the document already uses, both sections lifted into `requires:`,
 * and then the apply the instance refused -- one decision instead of a research task.
 */
export function ApplyDialog({
    open,
    mode,
    document,
    onOpenChange,
    onPlan,
    onApplied,
    onLift,
}: {
    open: boolean
    /** `apply` offers the button; `validate` shows the same answer without one. */
    mode: 'apply' | 'validate'
    document: JsonMap
    onOpenChange: (open: boolean) => void
    /** What the dry run said, so the screen can state it on the status bar. */
    onPlan?: (plan: PipelinePlan) => void
    onApplied: (result: ApplyResult) => void
    /** The same document with its carried sections named under `requires:`, or null. */
    onLift: () => JsonMap | null
}) {
    const [view, setView] = useState<PlanView | null>(null)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [applying, setApplying] = useState(false)
    const [held, setHeld] = useState<Held>(NOTHING_READ)
    const write = useMayWrite()
    const store = useMayWrite('admin')

    const carried = carriedRefusal(problem)

    useEffect(() => {
        if (!open) return
        let cancelled = false
        setView(null)
        setProblem(null)
        void applyPipeline(document, true).then(
            (result: ApplyResult) => {
                if (cancelled) return
                setView(planView(result.plan))
                onPlan?.(result.plan)
            },
            (error: unknown) => {
                if (!cancelled) setProblem(refusalOf(error))
            },
        )
        return () => {
            cancelled = true
        }
        // `onPlan` is the screen's own closure and changes with every render of it.
        // oxlint-disable-next-line react/exhaustive-deps
    }, [document, open])

    /**
     * What this instance holds under the codes the document carries, asked code by code.
     *
     * A listing is a page, and a page is not an answer to "is there one coded this": a schema on
     * the second page would be reported missing and the create would then collide. Each code is
     * read by itself instead, which is a handful of requests and an exact answer, and a read
     * that refuses is taken as not there -- the create or the apply is what says otherwise.
     *
     * It runs only once a carried section is what was refused; a refusal this dialog cannot
     * answer asks the instance for nothing.
     */
    const readHeld = useCallback((asked: JsonMap) => {
        const codes = carriedCodes(asked)
        void Promise.all([
            Promise.allSettled(codes.schemas.map((code) => readSchema(code))),
            Promise.allSettled(codes.connections.map((code) => readConnection(code))),
        ]).then(([schemas, connections]) => {
            setHeld({
                schemas: schemas.flatMap((one) =>
                    one.status === 'fulfilled' ? [{ code: one.value.code, body: one.value.body }] : [],
                ),
                connections: connections.flatMap((one) =>
                    one.status === 'fulfilled' ? [one.value.code] : [],
                ),
            })
        })
    }, [])

    useEffect(() => {
        if (!carried) {
            setHeld(NOTHING_READ)
            return
        }
        readHeld(document)
    }, [carried, document, readHeld])

    const items = useMemo(
        () => (carried ? carriedItems(document, held, store.may) : []),
        [carried, document, held, store.may],
    )
    const reading = held.schemas === null || held.connections === null
    const blocked = carried ? offerBlocked(items) : undefined

    /**
     * Whether this dialog is a decision or a report.
     *
     * A DECISION NEEDS BOTH PATHS. Applying is offered only where pressing it would do
     * something: not in `validate`, which asks nothing; not while there is no plan yet or the
     * plan on screen is one the instance would refuse; and not where a carried code collides
     * with the instance's own or names a connection nobody has created. A confirm that cannot
     * proceed is a control claiming an outcome the situation does not have, so it is not drawn
     * at all and the sentence beside the rows is what says why. A control shut by who somebody
     * is stays drawn and says so, because that is a courtesy about the account rather than a
     * claim about the document.
     */
    const asks = mode === 'apply' && (carried ? blocked === undefined : view !== null && view.applicable)

    const apply = () => {
        setApplying(true)
        void applyPipeline(document, false).then(
            (result: ApplyResult) => {
                setApplying(false)
                onApplied(result)
                onOpenChange(false)
            },
            (error: unknown) => {
                setApplying(false)
                setProblem(refusalOf(error))
            },
        )
    }

    /**
     * Store what this instance should hold of what the document carries, then apply it lifted.
     *
     * The schemas are stored one at a time and in order, because the first refusal is the one
     * the reader has to answer and everything after it would be asked against a question
     * already lost. A refusal part way through has written what it wrote, so the listings are
     * read again and those rows read `already here`: pressing again finishes the job.
     *
     * AN APPLY THAT WROTE NOTHING IS NOT AN APPLY. `$apply` answers 200 with an `invalid` plan
     * rather than refusing, so the plan is read before anything is called applied -- otherwise
     * a document the instance would not take is announced as a version nobody wrote.
     */
    const goForward = () => {
        setApplying(true)
        setProblem(null)
        void (async () => {
            try {
                const made = creations(items)
                for (const item of made) {
                    // A create is a write whose refusal stops the rest; there is nothing to
                    // overlap and a second failure would bury the first.
                    // oxlint-disable-next-line no-await-in-loop
                    await createSchema(item.body ?? {}, item.code)
                }
                // A write is said once it has happened, whichever way the apply after it goes:
                // a plan that turns out to write nothing must not make a stored schema silent.
                if (made.length > 0) toast.success(storedNote(made))
                const lifted = onLift()
                if (lifted === null) {
                    setProblem(local(LABELS.editor.carried.lift_failed))
                    return
                }
                const result = await applyPipeline(lifted, false)
                const read = planView(result.plan)
                if (!read.applicable) {
                    // The lift wrote nothing new: the instance is already at this document,
                    // which is an outcome to report rather than a dialog to keep open.
                    if (result.plan.action === 'unchanged') {
                        toast.info(unchangedNote(result.plan))
                        onOpenChange(false)
                        return
                    }
                    setView(read)
                    onPlan?.(result.plan)
                    readHeld(document)
                    return
                }
                onApplied(result)
                onOpenChange(false)
            } catch (error: unknown) {
                setProblem(refusalOf(error))
                readHeld(document)
            } finally {
                setApplying(false)
            }
        })()
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            {/* ONE DISMISSAL, ONE CONTROL. The footer always carries the way out -- `Cancel`
                beside a confirm, `Close` where there is nothing to confirm -- so the corner's
                own is not drawn as well. */}
            <DialogContent className="sm:max-w-lg" showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>
                        {mode === 'apply' ? LABELS.editor.apply.title : LABELS.editor.apply.validate_title}
                    </DialogTitle>
                    {/* What is on screen is a dry run either way. Saying so above the button that
                        writes would be untrue of what pressing it does, so only Validate says it.
                        The carried line counts what applying stores, so it waits for the read
                        that settles the count rather than saying a number that then changes. */}
                    {carried
                        ? !reading && <DialogDescription>{offerNote(items)}</DialogDescription>
                        : mode === 'validate' && (
                              <DialogDescription>{LABELS.editor.apply.nothing_written}</DialogDescription>
                          )}
                </DialogHeader>

                {/* A CARRIED SECTION IS ANSWERED, NOT RESTATED. Every other refusal is drawn as
                    the server wrote it; this one has a list and controls under it that say the
                    same fact in the terms of this screen, so its sentence is not drawn twice. */}
                {problem !== null && !carried && <Refusal problem={problem} />}
                {carried && <CarriedOffer items={items} reading={reading} />}
                {problem === null && view === null && (
                    <p className="text-sm text-muted-foreground">{LABELS.editor.apply.checking}</p>
                )}
                {view !== null && <PlanReading view={view} />}

                {/* A DIALOG THAT ONLY TELLS HAS ONE CONTROL, AND IT SAYS DISMISSAL. There is
                    nothing to cancel where there was never a second path. */}
                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        {asks ? LABELS.action.cancel : LABELS.action.close}
                    </Button>
                    {asks && (
                        <Confirm
                            // The offer is checked against what this instance holds, and nothing
                            // is pressed on the strength of a read that has not landed. A plain
                            // plan asks the instance nothing extra and waits on nothing.
                            why={carried ? firstShut(write.why, unread(reading)) : write.why}
                            busy={applying}
                            onApply={carried ? goForward : apply}
                        />
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

/** Why going forward waits, which is what this instance holds, still being read. */
function unread(reading: boolean): string | undefined {
    return reading ? LABELS.editor.carried.unread : undefined
}

/** The button that writes, shut with the sentence saying why when it would not. */
function Confirm({ why, busy, onApply }: { why: string | undefined; busy: boolean; onApply: () => void }) {
    return (
        <Refusable why={why}>
            <Button disabled={busy || why !== undefined} title={why} onClick={onApply}>
                {LABELS.action.apply}
            </Button>
        </Refusable>
    )
}
