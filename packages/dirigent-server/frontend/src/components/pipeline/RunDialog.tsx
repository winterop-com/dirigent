import { useMemo, useState } from 'react'

import { GeneratedForm } from '@/components/schema/GeneratedForm'
import { SchemaIssueCount, useSchemaForm } from '@winterop-com/sokkel-ui/schema/SchemaForm'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@winterop-com/sokkel-ui/primitives/select'
import { DialogShell } from '@winterop-com/sokkel-ui/DialogShell'
import { useMayWrite } from '@/hooks/use-may-write'
import { useStore } from '@/hooks/use-store'
import { type JsonMap, type Problem } from '@/lib/api'
import { DIALOG_WORDS, FIELD_WORDS } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { refusalOf, said } from '@/lib/refusal'
import { headingOf, type Addressable } from '@/lib/identity'
import { paramsOf, startRun, type RunAccepted } from '@/lib/pipelines'
import { readWindow, referencesWindow } from '@/lib/run-window'
import { handEntryOf } from '@/lib/sources'
import { formSchema, hasFields } from '@/lib/form-schema'
import { offsetMinutes, timesMode, zoneLabel } from '@/lib/times'
import { Callout } from '@winterop-com/sokkel-ui/Callout'
import { DateTimeField } from '@winterop-com/sokkel-ui/DateTimeField'
import { FieldGroup } from '@winterop-com/sokkel-ui/FieldGroup'
import { InlineField } from '@winterop-com/sokkel-ui/InlineField'

const ENTRY = LABELS.editor.run.entry

/**
 * Starting one ad hoc run of the version this instance holds.
 *
 * A REQUIRED FIELD IS NOT A COMPLAINT UNTIL SOMEBODY HAS BEEN THERE. A field says what is wrong
 * with it once it has been left with a value or a run was asked for; asking shows every issue,
 * counts them beside the verb, and starts nothing while one stands, a box that does not parse
 * among them.
 *
 * THE FORM IS THE PIPELINE'S OWN PARAMETER SCHEMA, drawn by the same `GeneratedForm` a block's
 * config form is, so a parameter this pipeline does not take has no box.
 *
 * A WINDOW IS ASKED FOR WHERE THE DOCUMENT READS ONE. A step writing `${run.window.start}`
 * fails on a run carrying no window, so the section stands open and the button is shut until
 * both instants are there; a document reading none is offered the same two boxes behind a link,
 * because an ad hoc run of any pipeline may still want to say which interval it covers.
 *
 * IT RUNS THE STORED VERSION, NOT THE EDITED DOCUMENT. `$run` runs the pipeline's current
 * version; unapplied edits are not what starts. The footnote says who it runs as and how it is
 * attributed, which is what the run's own screen will then show.
 *
 * WHAT WILL FAIL IS SAID BEFORE IT IS STARTED, NOT AFTER. A document is portable and an
 * instance is not, so a step naming a block this instance has never installed will stop the
 * run at that step -- and the moment to read that is here, with the button still unpressed.
 * Starting is still offered: the server is the authority, and a reader who knows better than
 * a stale catalog read must not be blocked by it.
 */
export function RunDialog({
    open,
    pipeline,
    document,
    username,
    warnings,
    onOpenChange,
    onStarted,
}: {
    open: boolean
    /** The pipeline this runs, headed by its name and addressed by its code. */
    pipeline: Addressable
    /** The document the instance holds, which is what its parameters and its window are read from. */
    document: JsonMap | null
    /** Who the run will be attributed to, which is whoever is signed in. */
    username: string | null
    /** What this instance has not got of what the document names, one line each. */
    warnings: readonly string[]
    onOpenChange: (open: boolean) => void
    onStarted: (accepted: RunAccepted) => void
}) {
    const schema = useMemo(() => formSchema(paramsOf(document)), [document])
    const takes = hasFields(schema)
    const form = useSchemaForm(schema, { initial: {} })
    const needsWindow = useMemo(() => referencesWindow(document), [document])
    const entry = useMemo(() => handEntryOf(document), [document])
    const [windowStart, setWindowStart] = useState('')
    const [windowEnd, setWindowEnd] = useState('')
    const [windowAsked, setWindowAsked] = useState(false)
    const mode = useStore(timesMode)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [starting, setStarting] = useState(false)
    const [level, setLevel] = useState<'info' | 'debug'>('info')
    const write = useMayWrite()
    // Each end is read at its own wall clock, so a window that runs across the night the local
    // offset moves on still covers the interval it says it does.
    const window = readWindow(windowStart, windowEnd, needsWindow, (written) =>
        offsetMinutes(mode, new Date(`${written}:00`)),
    )

    const start = () => {
        if (!form.submit()) return
        setStarting(true)
        void startRun(
            pipeline.code,
            form.value as JsonMap,
            level === 'debug' ? { '*': 'debug' } : null,
            window.kind === 'window' ? window.window : null,
        ).then(
            (accepted) => {
                setStarting(false)
                onStarted(accepted)
                onOpenChange(false)
            },
            (error: unknown) => {
                setStarting(false)
                setProblem(refusalOf(error))
            },
        )
    }

    const heading = headingOf(pipeline)
    // Why the run cannot start: a role that may not, or a window this document reads and has
    // not been given. The role comes first, because nothing a viewer fills in would change it.
    const shut = write.why ?? (window.kind === 'unready' ? window.why : undefined)

    return (
        <DialogShell
            words={DIALOG_WORDS}
            open={open}
            onOpenChange={onOpenChange}
            // With no parameters to fill in there is one thing to do here, so that is what is in hand.
            initialFocus={takes ? undefined : 'confirm'}
            // The title is the verb alone, since the pipeline is named beneath it, drawn as the
            // quartet is drawn everywhere: the name, then the code in mono.
            title={LABELS.action.run}
            description={
                <>
                    <span className="text-foreground">{heading.title}</span>
                    {heading.code !== null && <span className="font-mono"> {heading.code}</span>}
                </>
            }
            count={<SchemaIssueCount form={form} />}
            confirm={{
                label: LABELS.editor.run.confirm,
                busy: starting,
                why: shut,
                onConfirm: start,
            }}
        >
            {takes && <GeneratedForm form={form} />}

            {needsWindow || windowAsked ? (
                <FieldGroup label={LABELS.word.window.label} hint={zoneLabel(mode)} keyHint>
                    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                        {[
                            {
                                id: 'run-window-start',
                                label: LABELS.word.start,
                                value: windowStart,
                                set: setWindowStart,
                            },
                            {
                                id: 'run-window-end',
                                label: LABELS.word.end,
                                value: windowEnd,
                                set: setWindowEnd,
                            },
                        ].map((end) => (
                            <DateTimeField
                                key={end.id}
                                id={end.id}
                                label={end.label}
                                required={needsWindow}
                                requiredMark="word"
                                words={FIELD_WORDS}
                                mono
                                value={end.value === '' ? null : end.value}
                                onValueChange={(next) => {
                                    end.set(next ?? '')
                                }}
                            />
                        ))}
                    </div>
                </FieldGroup>
            ) : (
                <Button
                    variant="link"
                    className="w-fit px-0 text-foreground underline-offset-2"
                    onClick={() => {
                        setWindowAsked(true)
                    }}
                >
                    {LABELS.editor.run.add_window}
                </Button>
            )}

            {warnings.length > 0 && (
                <Callout tone="warning">
                    {warnings.map((line) => (
                        <p key={line}>{line}</p>
                    ))}
                </Callout>
            )}

            {problem !== null && (
                <p className="text-xs text-critical" role="alert">
                    {said(problem)}
                </p>
            )}

            <InlineField id="run-log-level" label={LABELS.editor.run.log} size="sm" className="w-fit">
                <Select
                    value={level}
                    onValueChange={(chosen) => {
                        setLevel(chosen === 'debug' ? 'debug' : 'info')
                    }}
                >
                    <SelectTrigger
                        id="run-log-level"
                        size="sm"
                        className="w-40"
                        aria-label={LABELS.editor.run.log_level}
                    >
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="info">{LABELS.editor.run.info_and_up}</SelectItem>
                        <SelectItem value="debug">{LABELS.editor.run.debug_too}</SelectItem>
                    </SelectContent>
                </Select>
            </InlineField>

            {entry !== null && (
                <p className="text-xs text-muted-foreground" data-testid="run-entry">
                    {entry.sampled ? ENTRY.sample : ENTRY.empty}
                    <code className="font-mono text-[0.88em]">{entry.step}</code>
                    {entry.replies && ENTRY.no_caller}
                    {ENTRY.end}
                </p>
            )}

            <p className="text-xs text-faint">
                {LABELS.editor.run.runs_as(username ?? LABELS.editor.run.this_session)}
            </p>
        </DialogShell>
    )
}
