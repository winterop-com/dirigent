import { Ban, Copy, RotateCw, SquareTerminal } from 'lucide-react'
import { Suspense, lazy, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import { OutputTab } from '@/components/run/OutputTab'
import { ReportTab } from '@/components/run/ReportTab'
import { RunTab } from '@/components/run/RunTab'
import { RunTerminal } from '@/components/run/RunTerminal'
import { StatusChip } from '@/components/run/StatusChip'
import { StepTab } from '@/components/run/StepTab'
import { Breadcrumb } from '@/components/Breadcrumb'
import { PageState } from '@/components/PageState'
import { ToolbarActions } from '@/components/ToolbarActions'
import { sayRefusal } from '@/components/Refusal'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useMayWrite } from '@/hooks/use-may-write'
import { useStore } from '@/hooks/use-store'
import { ApiError, type JsonMap, type Problem } from '@/lib/api'
import { formatInstant } from '@/lib/format'
import { fillPanel, openPanel, openPanelTab, type PanelTab } from '@/lib/panels'
import { RUN_GROUP, registerActions } from '@/lib/palette'
import { readPipeline, startRun, stepsOf } from '@/lib/pipelines'
import { decodeFrame, reduce, resumeCursor, stepViews, type RunDetailState } from '@/lib/run-detail'
import { follow } from '@/lib/run-stream'
import { cancelRun, priorityMark, readReport, readRun, waitingForWorkers, type RunReport } from '@/lib/runs'
import { clearScreenStatus, setScreenStatus, streamNote } from '@/lib/screen-status'
import { runSettled } from '@/lib/status'
import { terminalOpen, toggleTerminal } from '@/lib/terminal'
import { cn } from '@/lib/utils'

/**
 * React Flow and elk are the largest thing this app depends on and only this screen draws a
 * graph, so they are fetched when a run is opened rather than shipped in the entry chunk.
 */
const RunGraph = lazy(() =>
    import('@/components/run/RunGraph').then((module) => ({ default: module.RunGraph })),
)

export const CANCEL_LABEL = 'Cancel this run'
export const RERUN_LABEL = 'Run this pipeline again'
export const TERMINAL_LABEL = "Show or hide this run's terminal"

/** How often the screen re-reads the clock while the run is live, for the retry countdowns. */
const TICK_MS = 1000

/**
 * One run: its graph, the step in front of somebody, and everything the run has said.
 *
 * ONE EVENT STREAM PER OPEN RUN. `GET /runs/{id}/$events` carries the attempt transitions, the
 * log lines and the ending down one connection; the log pane, the graph and the panel are three
 * readings of that one state and never three connections. `lib/run-stream` holds it open,
 * `lib/run-detail` is what a frame means, and this file is what the two of them look like.
 *
 * THE INITIAL READ IS THE GRAPH, THE STREAM IS EVERYTHING AFTER. `GET /runs/{id}` answers with
 * the pinned definition folded into nodes and edges, which is the only place that shape comes
 * from; the stream never re-sends it, so a step that appears mid-run does not exist.
 *
 * THE CANVAS AND THE TERMINAL STACK. The content area is a column -- the graph above, the
 * console below at the height somebody dragged it to -- and the right panel is untouched by
 * either, because what is beside a run is a different question from what is under it.
 */
export function RunDetail() {
    const { id = '' } = useParams()
    const navigate = useNavigate()
    const [state, dispatch] = useReducer(reduce, null)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [selected, setSelected] = useState<string | null>(null)
    const [document, setDocument] = useState<{ version: number | null; steps: Record<string, JsonMap> } | null>(null)
    const [report, setReport] = useState<RunReport | null>(null)
    const [reportProblem, setReportProblem] = useState<Problem | null>(null)
    const [now, setNow] = useState(() => Date.now())

    // The stream's loop reads the cursor and the run's status at connect time, which is long
    // after the render that produced them.
    const held = useRef<RunDetailState | null>(null)
    useEffect(() => {
        held.current = state
    }, [state])

    // NOTHING HELD HERE OUTLIVES THE RUN IT WAS READ FOR. The attempts, the log tail and the
    // cursor a reconnect resumes past all belong to one run, so opening another empties them in
    // the render that carries the new id, before any effect can reconnect a stream with them.
    const [opened, setOpened] = useState(id)
    if (opened !== id) {
        setOpened(id)
        dispatch({ kind: 'reset' })
        setProblem(null)
        setReport(null)
        setReportProblem(null)
    }

    useEffect(() => {
        let cancelled = false
        void readRun(id).then(
            (detail) => {
                if (cancelled) return
                setProblem(null)
                dispatch({ kind: 'loaded', detail })
            },
            (error: unknown) => {
                if (!cancelled) setProblem(error instanceof ApiError ? error.problem : null)
            },
        )
        return () => {
            cancelled = true
        }
    }, [id])

    // The stream is opened against the run this screen has actually read, never against the
    // route's id while the state still holds the run somebody came from.
    const ready = state !== null && state.run.id === id
    useEffect(() => {
        if (!ready) return
        const controller = new AbortController()
        void follow(id, {
            onFrame: (frame) => {
                dispatch({ kind: 'frame', frame: decodeFrame(frame) })
            },
            onState: (stream) => {
                dispatch({ kind: 'stream', stream })
            },
            cursor: () => (held.current === null ? null : resumeCursor(held.current)),
            settled: () => held.current !== null && runSettled(held.current.run.status),
            signal: controller.signal,
        })
        return () => {
            controller.abort()
        }
    }, [id, ready])

    const pipeline = state?.run.pipeline ?? null
    useEffect(() => {
        if (pipeline === null) return
        let cancelled = false
        void readPipeline(pipeline).then(
            (detail) => {
                if (!cancelled) setDocument({ version: detail.current_version, steps: stepsOf(detail.document) })
            },
            () => {
                // The pipeline was deleted, or this account may not read it. Every step still
                // has its status, its attempts and its logs; it is the config that is missing.
            },
        )
        return () => {
            cancelled = true
        }
    }, [pipeline])

    const settled = state !== null && runSettled(state.run.status)
    const waiting = state === null || settled ? null : waitingForWorkers(state.waitingForWorkers)
    const priority = state === null ? null : priorityMark(state.run.priority)
    useEffect(() => {
        if (!settled) return
        let cancelled = false
        void readReport(id).then(
            (summary) => {
                if (!cancelled) setReport(summary)
            },
            (error: unknown) => {
                if (!cancelled) setReportProblem(error instanceof ApiError ? error.problem : null)
            },
        )
        return () => {
            cancelled = true
        }
    }, [id, settled])

    // A retry says how long until its next poll, which is only true for as long as it is read.
    useEffect(() => {
        if (settled) return
        const timer = setInterval(() => {
            setNow(Date.now())
        }, TICK_MS)
        return () => {
            clearInterval(timer)
        }
    }, [settled])

    const stream = state?.stream ?? 'connecting'
    const trace = state?.run.trace_id ?? null
    useEffect(() => {
        const note = streamNote(stream)
        setScreenStatus({ note: note.note, tone: note.tone, identifier: trace })
        return clearScreenStatus
    }, [stream, trace])

    const views = useMemo(() => (state === null ? [] : stepViews(state, now)), [state, now])
    const chosen = views.find((view) => view.node.code === selected) ?? null
    const terminal = useStore(terminalOpen)
    const write = useMayWrite()

    // A line's step prefix and a node on the graph ask the same thing: read this step. The
    // prefix names the tab as well, because somebody clicking one is not asking for whichever
    // tab they last had open.
    const readStep = (step: string) => {
        setSelected(step)
        openPanelTab('step')
    }

    // A RE-RUN CARRIES THE WINDOW THE RUN CARRIED. What a windowed run covers is a fact about
    // that run, and a repeat of it over no interval at all would stop at the first step reading
    // an edge of one.
    const rerun = useMemo(() => {
        if (state === null) return null
        const run = state.run
        const window =
            run.window_start === null || run.window_end === null
                ? null
                : { window_start: run.window_start, window_end: run.window_end }
        return () => {
            void startRun(run.pipeline, run.params, null, window).then(
                (accepted) => {
                    if (accepted.run_id === null) {
                        toast.warning(accepted.detail ?? `nothing started: ${accepted.status}`)
                        return
                    }
                    void navigate(`/runs/${accepted.run_id}`)
                },
                sayRefusal,
            )
        }
    }, [navigate, state])

    const cancel = useMemo(() => {
        if (state === null || runSettled(state.run.status)) return null
        return () => {
            void cancelRun(id).then(
                (run) => {
                    dispatch({ kind: 'frame', frame: { kind: 'run', run } })
                },
                sayRefusal,
            )
        }
    }, [id, state])

    // The shelf names the run it is scoped to, because the palette lays a screen's own rows
    // out first and a heading saying only "Run" would not say which one. A run is named by
    // its pipeline and when it started; its id is a handle for machines.
    const shelf = state === null ? RUN_GROUP : `${RUN_GROUP} — ${state.run.pipeline} ${formatInstant(state.run.started_at ?? state.run.created_at)}`

    useEffect(() => {
        return registerActions([
            {
                id: 'run:terminal',
                title: TERMINAL_LABEL,
                group: shelf,
                screen: true,
                icon: SquareTerminal,
                keywords: ['console', 'logs', 'output', 'lines'],
                hint: 'Every line this run wrote, in the order it wrote them',
                run: toggleTerminal,
            },
            ...(cancel === null
                ? []
                : [
                      {
                          id: 'run:cancel',
                          title: CANCEL_LABEL,
                          group: shelf,
                          screen: true,
                          icon: Ban,
                          keywords: ['stop', 'abort'],
                          run: cancel,
                      },
                  ]),
            ...(rerun === null
                ? []
                : [
                      {
                          id: 'run:again',
                          title: RERUN_LABEL,
                          group: shelf,
                          screen: true,
                          icon: RotateCw,
                          keywords: ['repeat', 'retry'],
                          run: rerun,
                      },
                  ]),
            ...(trace === null
                ? []
                : [
                      {
                          id: 'run:trace',
                          title: 'Copy this run trace id',
                          group: shelf,
                          screen: true,
                          icon: Copy,
                          keywords: ['tracing', 'otel'],
                          hint: trace,
                          run: () => {
                              void navigator.clipboard?.writeText(trace).then(
                                  () => toast.success('trace id copied'),
                                  () => toast.error('this browser would not give up its clipboard'),
                              )
                          },
                      },
                  ]),
        ])
    }, [cancel, rerun, shelf, trace])

    const tabs = useMemo<PanelTab[]>(() => {
        if (state === null) return []
        return [
            {
                id: 'step',
                label: 'Step',
                render: () =>
                    chosen === null ? (
                        <p className="text-muted-foreground p-4 text-sm">No step chosen.</p>
                    ) : (
                        <StepTab
                            state={state}
                            view={chosen}
                            config={document?.steps[chosen.node.code] ?? null}
                            configVersion={{ shown: document?.version ?? null, pinned: state.run.pipeline_version }}
                        />
                    ),
            },
            { id: 'run', label: 'Run', render: () => <RunTab run={state.run} /> },
            {
                id: 'output',
                label: 'Output',
                render: () => <OutputTab state={state} runId={id} />,
            },
            {
                id: 'report',
                label: 'Report',
                render: () => (
                    <ReportTab
                        runId={id}
                        settled={runSettled(state.run.status)}
                        report={report}
                        problem={reportProblem}
                    />
                ),
            },
        ]
    }, [chosen, document, id, report, reportProblem, state])

    useEffect(() => fillPanel(tabs, { screen: `run:${id}`, open: 'step' }), [tabs, id])

    if (state === null) {
        return (
            <PageState loading={problem === null} problem={problem} empty={false}>
                {null}
            </PageState>
        )
    }

    return (
        <div className="-mx-1 -my-3 flex min-h-0 flex-1 flex-col gap-3 md:-mx-5">
            <div className="flex items-center gap-x-3">
                <Breadcrumb
                    trail={[
                        { label: 'Runs', to: '/runs' },
                        {
                            label: state.run.pipeline,
                            to: `/pipelines/${state.run.pipeline}`,
                            mono: true,
                            keep: true,
                        },
                        {
                            label: formatInstant(state.run.started_at ?? state.run.created_at),
                            mono: true,
                            title: state.run.id,
                        },
                    ]}
                />
                <StatusChip status={state.run.status} />
                {priority !== null && <span className={cn('text-xs', priority.className)}>{priority.label}</span>}
                {waiting !== null && <span className="text-warning text-xs">{waiting}</span>}
                <div className="flex-1" />
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="ghost"
                                size="icon-sm"
                                aria-label={TERMINAL_LABEL}
                                aria-pressed={terminal}
                                onClick={toggleTerminal}
                            >
                                <SquareTerminal className="size-4" aria-hidden />
                            </Button>
                        }
                    />
                    <TooltipContent side="bottom">{TERMINAL_LABEL}</TooltipContent>
                </Tooltip>
                <ToolbarActions
                    actions={[
                        ...(cancel === null
                            ? []
                            : [
                                  {
                                      id: 'cancel',
                                      label: 'Cancel',
                                      icon: Ban,
                                      destructive: true,
                                      disabled: !write.may,
                                      why: write.why,
                                      onClick: cancel,
                                  },
                              ]),
                        ...(rerun === null
                            ? []
                            : [
                                  {
                                      id: 'rerun',
                                      label: 'Re-run',
                                      icon: RotateCw,
                                      disabled: !write.may,
                                      why: write.why,
                                      onClick: rerun,
                                  },
                              ]),
                    ]}
                />
            </div>

            <div className="flex min-h-0 flex-1 flex-col">
                <div
                    className={cn(
                        'border-border-strong bg-background flex-1 overflow-hidden rounded-md border',
                        terminal ? 'min-h-48' : 'min-h-96',
                    )}
                >
                    {state.dag.nodes.length === 0 ? (
                        <p className="text-muted-foreground p-4 text-sm">
                            This run's pinned definition has no steps to draw.
                        </p>
                    ) : (
                        <Suspense
                            fallback={
                                <PageState loading problem={null} empty={false}>
                                    {null}
                                </PageState>
                            }
                        >
                            <RunGraph
                                dag={state.dag}
                                views={views}
                                selected={selected}
                                onSelect={(step) => {
                                    setSelected(step)
                                    if (step !== null) openPanel()
                                }}
                            />
                        </Suspense>
                    )}
                </div>
                {terminal && <RunTerminal state={state} runId={id} onSelectStep={readStep} />}
            </div>
        </div>
    )
}
