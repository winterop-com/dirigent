import { useMemo, useRef, useState } from 'react'

import { SchemaForm } from '@/components/pipeline/SchemaForm'
import { Refusable } from '@/components/Refusable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { useMayWrite } from '@/hooks/use-may-write'
import { useStore } from '@/hooks/use-store'
import { type JsonMap, type Problem } from '@/lib/api'
import { refusalOf } from '@/lib/refusal'
import { headingOf, type Addressable } from '@/lib/identity'
import { paramsOf, startRun, type RunAccepted } from '@/lib/pipelines'
import { readWindow, referencesWindow } from '@/lib/run-window'
import { fieldsOf, maySubmit, validateFields, withUnreadable } from '@/lib/schema-form'
import { offsetMinutes, timesMode, zoneLabel } from '@/lib/times'

/** The dialog's title: the verb alone, since the pipeline is named beneath it. */
export const RUN_TITLE = 'Run'

export const RUN_NOW_LABEL = 'Run now'

/**
 * Starting one ad hoc run of the version this instance holds.
 *
 * A REQUIRED FIELD IS NOT A COMPLAINT UNTIL SOMEBODY HAS BEEN THERE. Every empty required
 * parameter is a problem from the moment the dialog opens, and stating all of them at once
 * tells somebody off for opening it -- so the button stays disabled and the controls are
 * marked, and a field says what is wrong with it once it has been left or a run was asked for.
 *
 * A BOX THAT DOES NOT PARSE SHUTS THE BUTTON. The document keeps the last value that parsed, so
 * a run started over a half-written JSON parameter would start on something other than what is
 * on screen: an unreadable field blocks the start exactly as a refused value does.
 *
 * THE FORM IS THE PIPELINE'S OWN PARAMETER SCHEMA, read through the same `lib/schema-form` a
 * block's config form is built with, so a parameter this pipeline does not take has no box.
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
    const fields = useMemo(() => fieldsOf(paramsOf(document)), [document])
    const needsWindow = useMemo(() => referencesWindow(document), [document])
    const [values, setValues] = useState<JsonMap>({})
    const [windowStart, setWindowStart] = useState('')
    const [windowEnd, setWindowEnd] = useState('')
    const [windowAsked, setWindowAsked] = useState(false)
    const mode = useStore(timesMode)
    const [touched, setTouched] = useState<ReadonlySet<string>>(() => new Set())
    const [unreadable, setUnreadable] = useState<ReadonlySet<string>>(() => new Set())
    const [asked, setAsked] = useState(false)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [starting, setStarting] = useState(false)
    const [level, setLevel] = useState<'info' | 'debug'>('info')
    const write = useMayWrite()
    const problems = validateFields(fields, values)
    const stated = asked ? undefined : touched
    // Each end is read at its own wall clock, so a window that runs across the night the local
    // offset moves on still covers the interval it says it does.
    const window = readWindow(windowStart, windowEnd, needsWindow, (written) =>
        offsetMinutes(mode, new Date(`${written}:00`)),
    )
    // With no parameters to fill in there is one thing to do here, so that is what is in hand.
    const runNow = useRef<HTMLButtonElement>(null)

    const start = () => {
        setAsked(true)
        setStarting(true)
        void startRun(
            pipeline.code,
            values,
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
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-lg" initialFocus={fields.length === 0 ? runNow : undefined}>
                <DialogHeader>
                    <DialogTitle>{RUN_TITLE}</DialogTitle>
                    {/* The pipeline is the description, drawn as the quartet is drawn everywhere:
                        the name, then the code in mono, never the two glued into one sentence. */}
                    <DialogDescription>
                        <span className="text-foreground">{heading.title}</span>
                        {heading.code !== null && <span className="font-mono"> {heading.code}</span>}
                    </DialogDescription>
                </DialogHeader>

                {fields.length > 0 && (
                    <div className="max-h-[50vh] overflow-y-auto">
                        <SchemaForm
                            fields={fields}
                            values={values}
                            problems={problems}
                            stated={stated}
                            onChange={(name, value) => {
                                setValues((current) => {
                                    const next = { ...current }
                                    if (value === undefined) delete next[name]
                                    else next[name] = value
                                    return next
                                })
                            }}
                            onTouch={(name) => {
                                setTouched((current) => (current.has(name) ? current : new Set(current).add(name)))
                            }}
                            onUnreadable={(name, message) => {
                                setUnreadable((current) => withUnreadable(current, name, message))
                            }}
                        />
                    </div>
                )}

                {needsWindow || windowAsked ? (
                    <div className="space-y-2">
                        <div className="flex flex-wrap items-baseline gap-x-2">
                            <Label>Window</Label>
                            <span className="text-faint font-mono text-xs">{zoneLabel(mode)}</span>
                        </div>
                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                            <WindowField id="run-window-start" label="Start" value={windowStart} onChange={setWindowStart} />
                            <WindowField id="run-window-end" label="End" value={windowEnd} onChange={setWindowEnd} />
                        </div>
                    </div>
                ) : (
                    <Button
                        variant="link"
                        className="text-primary-ink w-fit px-0"
                        onClick={() => {
                            setWindowAsked(true)
                        }}
                    >
                        Add a window
                    </Button>
                )}

                {warnings.length > 0 && (
                    <div className="border-warning/40 bg-warning/10 space-y-0.5 rounded-md border p-2">
                        {warnings.map((line) => (
                            <p key={line} className="text-warning-ink text-xs">
                                {line}
                            </p>
                        ))}
                    </div>
                )}

                {problem !== null && (
                    <p className="text-critical text-xs" role="alert">
                        {problem.detail}
                    </p>
                )}

                <div className="flex items-center gap-2">
                    <span className="text-muted-foreground text-xs">log</span>
                    <Select
                        value={level}
                        onValueChange={(chosen) => {
                            setLevel(chosen === 'debug' ? 'debug' : 'info')
                        }}
                    >
                        <SelectTrigger size="sm" className="w-40" aria-label="log level">
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="info">info and up</SelectItem>
                            <SelectItem value="debug">debug too</SelectItem>
                        </SelectContent>
                    </Select>
                </div>

                <p className="text-faint text-xs">runs as {username ?? 'this session'} · adhoc</p>

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        Cancel
                    </Button>
                    <Refusable why={shut}>
                        <Button
                            ref={runNow}
                            disabled={starting || !write.may || !maySubmit(problems, unreadable) || shut !== undefined}
                            title={shut}
                            onClick={start}
                        >
                            {RUN_NOW_LABEL}
                        </Button>
                    </Refusable>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}

/** One end of the window: a wall clock to the minute, on the house field. */
function WindowField({
    id,
    label,
    value,
    onChange,
}: {
    id: string
    label: string
    value: string
    onChange: (value: string) => void
}) {
    return (
        <div className="space-y-2">
            <Label htmlFor={id}>{label}</Label>
            <Input
                id={id}
                type="datetime-local"
                className="font-mono"
                value={value}
                onChange={(event) => {
                    onChange(event.target.value)
                }}
            />
        </div>
    )
}
