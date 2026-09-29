import { useEffect, useState } from 'react'

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
import { LABELS } from '@/lib/labels'
import { refusalOf } from '@/lib/refusal'
import { planView, type PlanView } from '@/lib/pipeline-plan'
import { applyPipeline, type ApplyResult, type PipelinePlan } from '@/lib/pipelines'
import { firstShut } from '@/lib/roles'

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
 */
export function ApplyDialog({
    open,
    mode,
    document,
    onOpenChange,
    onPlan,
    onApplied,
}: {
    open: boolean
    /** `apply` offers the button; `validate` shows the same answer without one. */
    mode: 'apply' | 'validate'
    document: JsonMap
    onOpenChange: (open: boolean) => void
    /** What the dry run said, so the screen can state it on the status bar. */
    onPlan?: (plan: PipelinePlan) => void
    onApplied: (result: ApplyResult) => void
}) {
    const [view, setView] = useState<PlanView | null>(null)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [applying, setApplying] = useState(false)
    const write = useMayWrite()

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

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-lg">
                <DialogHeader>
                    <DialogTitle>
                        {mode === 'apply' ? LABELS.editor.apply.title : LABELS.editor.apply.validate_title}
                    </DialogTitle>
                    {/* What is on screen is a dry run either way. Saying so above the button that
                        writes would be untrue of what pressing it does, so only Validate says it. */}
                    {mode === 'validate' && (
                        <DialogDescription>{LABELS.editor.apply.nothing_written}</DialogDescription>
                    )}
                </DialogHeader>

                {problem !== null && <Refusal problem={problem} />}
                {problem === null && view === null && (
                    <p className="text-sm text-muted-foreground">{LABELS.editor.apply.checking}</p>
                )}
                {view !== null && <PlanReading view={view} />}

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        {mode === 'apply' ? LABELS.action.cancel : LABELS.action.close}
                    </Button>
                    {mode === 'apply' && (
                        <Confirm
                            why={firstShut(write.why, unapplicable(view))}
                            busy={applying}
                            onApply={apply}
                        />
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

/** Why the plan on screen cannot be applied, or nothing when it can. */
function unapplicable(view: PlanView | null): string | undefined {
    if (view === null) return LABELS.editor.apply.unchecked
    return view.applicable ? undefined : LABELS.editor.apply.unacceptable
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
