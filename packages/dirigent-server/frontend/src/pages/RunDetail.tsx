import { Suspense, lazy, useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'

import { OutputTab } from '@/components/run/OutputTab'
import { ReportTab } from '@/components/run/ReportTab'
import { RunTab } from '@/components/run/RunTab'
import { RunTerminal } from '@/components/run/RunTerminal'
import { StatusChip } from '@/components/run/StatusChip'
import { StepTab } from '@/components/run/StepTab'
import { Breadcrumb } from '@/components/Breadcrumb'
import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { IconButton } from '@winterop-com/sokkel-ui/IconButton'
import { PageHeader as LibraryPageHeader } from '@winterop-com/sokkel-ui/PageHeader'
import { Notice } from '@/components/ds/Notice'
import { Panel } from '@/components/ds/Panel'
import { PrimaryAction } from '@/components/ds/PrimaryAction'
import { connectionOf, RunFailure } from '@/components/run/RunFailure'
import { PageHead } from '@/components/PageHead'
import { PageState } from '@/components/PageState'
import { sayRefusal } from '@/components/Refusal'
import { useMayWrite } from '@/hooks/use-may-write'
import { useRead } from '@/hooks/use-read'
import { useSmallScreen } from '@/hooks/use-small-screen'
import { useStore } from '@/hooks/use-store'
import { readConnections } from '@/lib/connections'
import { shutWith, TOOLBAR_WORDS } from '@/lib/design-system'
import { ICONS } from '@/lib/icons'
import { ApiError, type JsonMap, type Problem } from '@/lib/api'
import { elapsedBetween, formatBytes, formatDuration, formatInstant } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import { problemsIn } from '@/lib/refusal'
import { fillPanel, openPanel, openPanelTab, panelOpen, panelSheet, type PanelTab } from '@/lib/panels'
import { RUN_GROUP, registerActions } from '@/lib/palette'
import { readPipeline, startRun, stepsOf } from '@/lib/pipelines'
import { decodeFrame, reduce, resumeCursor, stepViews, type RunDetailState } from '@/lib/run-detail'
import { follow } from '@/lib/run-stream'
import {
    cancelRun,
    pauseRun,
    priorityMark,
    readReport,
    readRun,
    resumeRun,
    runVerbs,
    startedBy,
    tabFromQuery,
    waitingForWorkers,
    type RunReport,
} from '@/lib/runs'
import { clearScreenStatus, setScreenStatus, streamNote } from '@/lib/screen-status'
import { runSettled } from '@/lib/status'
import {
    ATTEMPT_PARAM,
    chosenStep,
    ITEM_PARAM,
    queryForStep,
    queryWith,
    runStepPath,
} from '@/lib/step-address'
import { openTerminal, terminalOpen, toggleTerminal } from '@/lib/terminal'
import { cn } from '@/lib/utils'

/**
 * Only this screen and the pipeline editor draw a graph, so React Flow is fetched when a run is
 * opened rather than shipped in the entry chunk. elk follows when the canvas asks for geometry.
 */
const RunGraph = lazy(() =>
    import('@/components/run/RunGraph').then((module) => ({ default: module.RunGraph })),
)

export const CANCEL_LABEL = LABELS.runs.cancel_action
export const RERUN_LABEL = LABELS.runs.rerun_action
export const TERMINAL_LABEL = LABELS.runs.toggle_terminal

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
 * THE CANVAS AND THE TERMINAL STACK. The content area is a column -- the graph above, filling
 * what the page leaves it, the console below at the height somebody dragged it to -- and the
 * right panel is untouched by either, because what is beside a run is a different question from
 * what is under it.
 *
 * THE CHOSEN STEP IS THE ADDRESS. `/runs/<id>/<step>` is the run with that step chosen and its
 * panel open; choosing another replaces the address rather than adding one, so Back leaves the run.
 */
export function RunDetail() {
    const { id = '', step: addressed } = useParams()
    const navigate = useNavigate()
    const [state, dispatch] = useReducer(reduce, null)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [query] = useSearchParams()
    const search = query.toString()
    const chosenAt = chosenStep(addressed, state === null ? null : state.dag.nodes.map((node) => node.code))
    const selected = chosenAt.kind === 'step' ? chosenAt.code : null
    const [document, setDocument] = useState<{
        version: number | null
        name: string | null
        steps: Record<string, JsonMap>
    } | null>(null)
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
                if (!cancelled)
                    setDocument({
                        version: detail.current_version,
                        name: detail.name,
                        steps: stepsOf(detail.document),
                    })
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

    // Choosing a step replaces the address, so Back leaves the run rather than walking its steps.
    const select = useCallback(
        (step: string | null) => {
            void navigate(`${runStepPath(id, step)}${queryForStep(search)}`, { replace: true })
        },
        [id, navigate, search],
    )
    // An element or a try of the chosen step is named in the query, the same way.
    const nameInQuery = useCallback(
        (name: string, value: string | null) => {
            void navigate(`${runStepPath(id, addressed ?? null)}${queryWith(search, name, value)}`, {
                replace: true,
            })
        },
        [addressed, id, navigate, search],
    )
    const chosenItem = selected === null ? null : query.get(ITEM_PARAM)
    const chosenAttempt = selected === null ? null : query.get(ATTEMPT_PARAM)

    // A step the address chose opens the panel for this visit.
    useEffect(() => {
        if (selected !== null) openPanel()
    }, [selected])

    // Closing the panel puts the step down, so the address says what the screen shows.
    const small = useSmallScreen()
    const standing = useStore(small ? panelSheet : panelOpen)
    const stood = useRef(standing)
    useEffect(() => {
        const was = stood.current
        stood.current = standing
        if (was && !standing && selected !== null) select(null)
    }, [select, selected, standing])

    // A line's step prefix and a node on the graph ask the same thing: read this step. The
    // prefix names the tab as well, because somebody clicking one is not asking for whichever
    // tab they last had open.
    const readStep = (step: string) => {
        select(step)
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
            void startRun(run.pipeline, run.params, null, window).then((accepted) => {
                if (accepted.run_id === null) {
                    toast.warning(accepted.detail ?? LABELS.runs.nothing_started(accepted.status))
                    return
                }
                void navigate(`/runs/${accepted.run_id}`)
            }, sayRefusal)
        }
    }, [navigate, state])

    // A verb that changes what the run is doing answers with the run, which is folded in like a frame.
    const pause = () => {
        void pauseRun(id).then((run) => {
            dispatch({ kind: 'frame', frame: { kind: 'run', run } })
        }, sayRefusal)
    }
    const resume = () => {
        void resumeRun(id).then((run) => {
            dispatch({ kind: 'frame', frame: { kind: 'run', run } })
        }, sayRefusal)
    }
    const connectionsRead = useRead(useCallback(() => readConnections(null), []))
    const connections = connectionsRead.value?.items ?? []

    const cancel = useMemo(() => {
        if (state === null || runSettled(state.run.status)) return null
        return () => {
            void cancelRun(id).then((run) => {
                dispatch({ kind: 'frame', frame: { kind: 'run', run } })
            }, sayRefusal)
        }
    }, [id, state])

    // The shelf names the run it is scoped to, because the palette lays a screen's own rows
    // out first and a heading saying only "Run" would not say which one. A run is named by
    // its pipeline and when it started; its id is a handle for machines.
    const shelf =
        state === null
            ? RUN_GROUP
            : `${RUN_GROUP} — ${state.run.pipeline} ${formatInstant(state.run.started_at ?? state.run.created_at)}`

    useEffect(() => {
        return registerActions([
            {
                id: 'run:terminal',
                title: TERMINAL_LABEL,
                group: shelf,
                screen: true,
                icon: ICONS.terminal,
                keywords: ['console', 'logs', 'output', 'lines'],
                hint: LABELS.runs.terminal_hint,
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
                          icon: ICONS.cancel,
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
                          icon: ICONS.rerun,
                          keywords: ['repeat', 'retry'],
                          run: rerun,
                      },
                  ]),
            ...(trace === null
                ? []
                : [
                      {
                          id: 'run:trace',
                          title: LABELS.runs.copy_trace_action,
                          group: shelf,
                          screen: true,
                          icon: ICONS.copy,
                          keywords: ['tracing', 'otel'],
                          hint: trace,
                          run: () => {
                              void navigator.clipboard?.writeText(trace).then(
                                  () => toast.success(LABELS.runs.trace_copied),
                                  () => toast.error(LABELS.runs.clipboard_refused),
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
                label: LABELS.word.step.label,
                render: () =>
                    chosen === null ? (
                        <p className="p-4 text-sm text-muted-foreground">{LABELS.runs.no_step_chosen}</p>
                    ) : (
                        <StepTab
                            state={state}
                            view={chosen}
                            config={document?.steps[chosen.node.code] ?? null}
                            configVersion={{
                                shown: document?.version ?? null,
                                pinned: state.run.pipeline_version,
                            }}
                            chosenItem={chosenItem}
                            chosenAttempt={chosenAttempt}
                            onItem={(item) => {
                                nameInQuery(ITEM_PARAM, item)
                            }}
                            onAttempt={(attempt) => {
                                nameInQuery(ATTEMPT_PARAM, attempt)
                            }}
                        />
                    ),
            },
            {
                id: 'run',
                label: LABELS.word.run.label,
                render: () => <RunTab run={state.run} attempts={Object.values(state.attempts)} />,
            },
            {
                id: 'output',
                label: LABELS.word.output,
                render: () => <OutputTab state={state} runId={id} />,
            },
            {
                id: 'report',
                label: LABELS.word.report,
                render: () => (
                    <ReportTab
                        runId={id}
                        settled={runSettled(state.run.status)}
                        report={report}
                        problem={reportProblem}
                        attempts={Object.values(state.attempts)}
                    />
                ),
            },
        ]
    }, [chosen, chosenAttempt, chosenItem, document, id, nameInQuery, report, reportProblem, state])

    // An address naming a tab opens the panel on it for this visit, before the first fill.
    const askedTab = tabFromQuery(query)
    useEffect(() => {
        if (askedTab !== null) openPanel()
    }, [askedTab])
    useEffect(() => fillPanel(tabs, { screen: `run:${id}`, open: askedTab ?? 'step' }), [tabs, id, askedTab])

    const failedRun = state?.run.status === 'failed'
    useEffect(() => {
        if (failedRun) openTerminal()
    }, [failedRun])

    if (state === null) {
        return (
            <PageState loading={problem === null} problem={problem} empty={false}>
                {null}
            </PageState>
        )
    }

    const verbs = runVerbs(state.run.status)
    const run = state.run
    const stepFailed =
        run.failed_step ?? state.dag.nodes.find((node) => node.outcome === 'failed')?.code ?? null
    // A run that completed with errors may have failed in an item of a step rather than in the step.
    const itemFailed =
        stepFailed === null && run.status === 'completed_with_errors'
            ? (Object.values(state.attempts).find((attempt) => attempt.status === 'failed')?.step_name ??
              null)
            : null
    const failedAt = stepFailed ?? itemFailed
    const failedNode = state.dag.nodes.find((node) => node.code === failedAt) ?? null
    const failedAttempt =
        failedAt === null
            ? null
            : (Object.values(state.attempts).find(
                  (attempt) => attempt.step_name === failedAt && attempt.status === 'failed',
              ) ?? null)
    const named = connectionOf(
        failedAt === null ? null : ((document?.steps[failedAt]?.config as JsonMap | undefined) ?? null),
    )
    const troubled = run.status === 'failed' || run.status === 'completed_with_errors'
    const took = elapsedBetween(run.started_at, run.finished_at)
    const trigger = startedBy(run, Object.values(state.attempts))

    // The page scrolls above the terminal, which stands at the foot of the content area. The graph
    // takes whatever height the column has left over, and never less than its drawing needs.
    return (
        <div className="flex min-w-0 flex-1 flex-col">
            <div className="flex flex-1 flex-col pb-6">
                <PageHead>
                    <Breadcrumb
                        trail={[
                            { label: LABELS.screen.runs.name, to: '/runs' },
                            {
                                label: document?.name ?? run.pipeline,
                                to: `/pipelines/${run.pipeline}`,
                                mono: document === null || document.name === null,
                            },
                        ]}
                    />
                    <LibraryPageHeader
                        title={document?.name ?? run.pipeline}
                        code={run.pipeline}
                        singleLine={document === null || document.name === null}
                        meta={
                            <span title={run.id}>
                                <InlineCode
                                    value={formatInstant(run.started_at ?? run.created_at)}
                                    tone="muted"
                                    bare
                                    size="xs"
                                    className="pointer-events-none"
                                />
                            </span>
                        }
                        lead={
                            <IconButton
                                size="icon-sm"
                                label={TERMINAL_LABEL}
                                pressed={terminal}
                                onClick={toggleTerminal}
                            >
                                <ICONS.terminal aria-hidden />
                            </IconButton>
                        }
                        items={
                            // A settled run will never be paused, resumed or cancelled, so those
                            // three are not drawn on one; Rerun stands alone.
                            settled
                                ? []
                                : [
                                      {
                                          id: 'pause',
                                          label: LABELS.action.pause,
                                          icon: <ICONS.pause aria-hidden />,
                                          ...shutWith(
                                              !write.may || !verbs.pause.open,
                                              write.why ?? verbs.pause.why,
                                          ),
                                          onSelect: pause,
                                      },
                                      {
                                          id: 'resume',
                                          label: LABELS.action.resume,
                                          icon: <ICONS.resume aria-hidden />,
                                          ...shutWith(
                                              !write.may || !verbs.resume.open,
                                              write.why ?? verbs.resume.why,
                                          ),
                                          onSelect: resume,
                                      },
                                      {
                                          id: 'cancel',
                                          label: LABELS.action.cancel_run,
                                          icon: <ICONS.cancel aria-hidden />,
                                          destructive: verbs.cancel.open,
                                          ...shutWith(
                                              !write.may || !verbs.cancel.open || cancel === null,
                                              write.why ?? verbs.cancel.why,
                                          ),
                                          onSelect: () => {
                                              cancel?.()
                                          },
                                      },
                                  ]
                        }
                        actions={
                            <PrimaryAction
                                item={{
                                    id: 'rerun',
                                    label: LABELS.action.rerun,
                                    icon: <ICONS.rerun aria-hidden />,
                                    variant: verbs.rerun.open ? 'default' : 'outline',
                                    ...shutWith(
                                        !write.may || !verbs.rerun.open || rerun === null,
                                        write.why ?? verbs.rerun.why,
                                    ),
                                    onSelect: () => {
                                        rerun?.()
                                    },
                                }}
                            />
                        }
                        words={TOOLBAR_WORDS}
                    />

                    <div className="mt-4 flex flex-wrap items-center gap-x-4.5 gap-y-2 text-sm">
                        <StatusChip status={run.status} className="text-sm" />
                        {failedAt !== null && troubled && (
                            <span>
                                {LABELS.runs.line.at}{' '}
                                <InlineCode
                                    value={failedAt}
                                    className="font-medium"
                                    tone="neutral"
                                    bare
                                    size="sm"
                                />
                            </span>
                        )}
                        {took !== null && (
                            <span className="font-mono text-muted-foreground">{formatDuration(took)}</span>
                        )}
                        <span className="text-muted-foreground">{trigger}</span>
                        {run.stored_bytes > 0 && (
                            <span
                                className="text-muted-foreground"
                                title={LABELS.runs.line.stored(String(run.stored_bytes))}
                            >
                                {LABELS.runs.line.stored(formatBytes(run.stored_bytes))}
                            </span>
                        )}
                        {priority !== null && (
                            <span className={cn('text-xs', priority.className)}>{priority.label}</span>
                        )}
                        {waiting !== null && <span className="text-xs text-warning">{waiting}</span>}
                    </div>
                </PageHead>

                {chosenAt.kind === 'unknown' && (
                    <Notice tone="warning" className="mt-3.5">
                        {LABELS.runs.no_such_step(chosenAt.code)}
                    </Notice>
                )}

                <div className="mt-3.5 flex flex-1 flex-col">
                    {state.dag.nodes.length === 0 ? (
                        <Panel title={LABELS.pipelines.page.graph} tone="graph" inset={false}>
                            <p className="p-4 text-sm text-muted-foreground">{LABELS.runs.graph_empty}</p>
                        </Panel>
                    ) : (
                        <Suspense
                            fallback={
                                <Panel title={LABELS.pipelines.page.graph} tone="graph" inset={false}>
                                    <PageState loading problem={null} empty={false}>
                                        {null}
                                    </PageState>
                                </Panel>
                            }
                        >
                            <RunGraph
                                key={id}
                                name={run.pipeline}
                                dag={state.dag}
                                views={views}
                                selected={selected}
                                onSelect={select}
                            />
                        </Suspense>
                    )}
                </div>

                {troubled && (
                    <div className="mt-5">
                        <RunFailure
                            run={run}
                            step={failedAt}
                            items={itemFailed !== null}
                            error={failedAttempt?.error ?? run.error}
                            code={failedAttempt?.error_code ?? run.error_code}
                            problems={problemsIn(failedAttempt?.error_params)}
                            block={failedNode?.block ?? null}
                            connection={
                                named === null
                                    ? null
                                    : (connections.find((row) => row.code === named) ?? null)
                            }
                        />
                    </div>
                )}
            </div>
            {terminal && (
                <div className="sticky -bottom-12 -mb-12 flex flex-col bg-background pb-3">
                    <RunTerminal state={state} runId={id} step={selected} onSelectStep={readStep} />
                </div>
            )}
        </div>
    )
}
