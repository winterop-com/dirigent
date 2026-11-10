import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import { HealthSaid } from '@/components/connections/Health'
import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { Callout } from '@winterop-com/sokkel-ui/Callout'
import { PageHeader } from '@/components/ds/PageHeader'
import { Section } from '@winterop-com/sokkel-ui/Section'
import { Instant } from '@/components/Instant'
import { Markdown } from '@/components/Markdown'
import { PageState } from '@/components/PageState'
import { LatestReport, RecentRuns, RECENT_ROWS, REPORT_RUNS } from '@/components/pipeline/PipelineRuns'
import { RunDialog } from '@/components/pipeline/RunDialog'
import { ShapeGraph } from '@/components/pipeline/ShapeGraph'
import { TagChips } from '@/components/TagChips'
import { EndpointAddress, NewToken } from '@/components/triggers/Endpoint'
import { useMayWrite } from '@/hooks/use-may-write'
import { useRead } from '@/hooks/use-read'
import { useStore } from '@/hooks/use-store'
import { authStore } from '@/lib/auth'
import { healthOf, readConnections, type ConnectionOut } from '@/lib/connections'
import { shutWith } from '@/lib/design-system'
import { titleOf } from '@/lib/identity'
import { ICONS } from '@/lib/icons'
import { counted, LABELS } from '@/lib/labels'
import { reportIn } from '@/lib/pipeline-document'
import { applyPipeline, readPipeline, type StepShape } from '@/lib/pipelines'
import { EVERY_RUN, readRuns, readSettledRuns } from '@/lib/runs'
import { connectionsNamed } from '@/lib/requirements'
import { authLine, readPipelineSources, sampleBody, type SourceOut } from '@/lib/sources'
import type { JsonMap } from '@/lib/api'
import { sayRefusal } from '@/components/Refusal'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { chosenStep, pipelineStepPath } from '@/lib/step-address'
import { clockOf, nextFireView, readSchedules, type ScheduleOut } from '@/lib/triggers'
import { cn } from '@/lib/utils'

/** The address of a pipeline's editor. */
export function editorPath(code: string): string {
    return `/pipelines/${encodeURIComponent(code)}/edit`
}

/**
 * One pipeline, led by its graph.
 *
 * THE GRAPH FIRST, THEN WHAT IT DID, THEN WHAT IT RUNS, WHAT FIRES IT AND WHAT IT REACHES. What it
 * did is its newest runs and, where the document declares a report, the latest settled run's
 * document. The heading carries the
 * three verbs: Edit opens the editor, Validate dry-runs the stored version against the instance
 * as it is now, and `Run…` asks for what a run needs. Nothing on this page writes the document.
 */
export function PipelinePage() {
    const { code = '', step: addressed } = useParams()
    const navigate = useNavigate()
    const auth = useStore(authStore)
    const write = useMayWrite()
    const detail = useRead(useCallback(() => readPipeline(code), [code]))
    const schedules = useRead(useCallback(() => readSchedules(code, null), [code]))
    const held = useRead(useCallback(() => readConnections(null), []))
    const listening = useRead(useCallback(() => readPipelineSources(code), [code]))
    const recent = useRead(
        useCallback(() => readRuns({ ...EVERY_RUN, pipeline: code }, null, RECENT_ROWS), [code]),
    )
    const declared = reportIn(detail.value?.document ?? null).declared
    const settled = useRead(
        useCallback(
            () => (declared ? readSettledRuns(code, REPORT_RUNS) : Promise.resolve(null)),
            [code, declared],
        ),
    )
    // A verb on a source answers with its row as it now stands, over the page it was read on.
    const [fresher, setFresher] = useState<Record<string, SourceOut>>({})
    const [running, setRunning] = useState(false)
    const [validating, setValidating] = useState(false)

    const pipeline = detail.value
    // The chosen step is the address, replaced rather than added to, so Back leaves the page.
    const chosenAt = chosenStep(addressed, pipeline === null ? null : pipeline.shape.map((step) => step.code))
    const selected = chosenAt.kind === 'step' ? chosenAt.code : null
    const select = useCallback(
        (step: string | null) => {
            void navigate(pipelineStepPath(code, step), { replace: true })
        },
        [code, navigate],
    )
    const version = pipeline === null ? null : pipeline.current_version
    useEffect(() => {
        setScreenStatus({
            note: null,
            tone: 'quiet',
            identifier: version === null ? null : `v${String(version)}`,
        })
        return clearScreenStatus
    }, [version])

    const validate = useCallback(() => {
        if (pipeline === null || pipeline.document === null) return
        setValidating(true)
        void applyPipeline(pipeline.document, true)
            .then((result) => {
                const issues = result.plan.issues.length
                if (issues === 0) toast.success(LABELS.pipelines.page.valid)
                else toast.warning(counted(issues, LABELS.pipelines.page.invalid)(String(issues)))
            }, sayRefusal)
            .finally(() => {
                setValidating(false)
            })
    }, [pipeline])

    if (pipeline === null) {
        return (
            <PageState loading={detail.problem === null} problem={detail.problem} empty={false}>
                {null}
            </PageState>
        )
    }

    const steps = pipeline.shape
    const reported = settled.value?.items ?? []
    const noVersion = pipeline.document === null
    return (
        <div className="flex min-w-0 flex-col">
            <PageHeader
                title={titleOf(pipeline)}
                code={pipeline.code}
                trail={[{ label: LABELS.screen.pipelines.name, href: '/pipelines' }]}
                items={[
                    {
                        id: 'edit',
                        label: LABELS.action.edit,
                        icon: <ICONS.edit aria-hidden />,
                        onSelect: () => {
                            void navigate(editorPath(pipeline.code))
                        },
                    },
                    {
                        id: 'validate',
                        label: LABELS.action.validate,
                        onSelect: validate,
                        ...shutWith(
                            !write.may || noVersion || validating,
                            write.why ?? (noVersion ? LABELS.editor.canvas.nothing_to_draw : undefined),
                        ),
                    },
                ]}
                primary={{
                    id: 'run',
                    label: LABELS.action.asks(LABELS.action.run),
                    icon: <ICONS.run aria-hidden />,
                    onSelect: () => {
                        setRunning(true)
                    },
                    ...shutWith(
                        !write.may || noVersion || !pipeline.active,
                        write.why ??
                            (noVersion
                                ? LABELS.editor.topbar.not_applied
                                : pipeline.active
                                  ? undefined
                                  : LABELS.pipelines.deactivated.explained),
                    ),
                }}
            />

            {(pipeline.description !== null || pipeline.tags.length > 0) && (
                <div className="mt-4 max-w-[820px] text-base">
                    {pipeline.description !== null && <Markdown text={pipeline.description} />}
                    {pipeline.tags.length > 0 && (
                        <div className="mt-2.5">
                            <TagChips tags={pipeline.tags} />
                        </div>
                    )}
                </div>
            )}

            {chosenAt.kind === 'unknown' && (
                <Callout tone="warning" className="mt-6">
                    {LABELS.pipelines.page.no_such_step(chosenAt.code)}
                </Callout>
            )}

            {steps.length === 0 ? (
                <Section title={LABELS.pipelines.page.graph} tone="graph" flush className="mt-6">
                    <p className="p-4 text-sm text-muted-foreground">
                        {LABELS.editor.canvas.nothing_to_draw}
                    </p>
                </Section>
            ) : (
                <ShapeGraph
                    key={pipeline.code}
                    name={pipeline.code}
                    steps={steps}
                    selected={selected}
                    onSelect={select}
                >
                    {selected !== null && <ChosenStep steps={steps} code={selected} />}
                </ShapeGraph>
            )}

            <div className="mt-5 flex flex-wrap items-start gap-5">
                <RecentRuns
                    pipeline={pipeline.code}
                    runs={recent.value?.items ?? null}
                    problem={recent.problem}
                    className="flex-[1_1_420px]"
                />
                {/* The same bases as the row under it, so the seams between the two rows line up. */}
                {reported.length > 0 && <LatestReport runs={reported} className="flex-[1_1_300px]" />}
            </div>

            <div className="mt-5 flex flex-wrap items-start gap-5">
                {steps.some((step) => step.kind === 'block') && (
                    <Section
                        title={LABELS.pipelines.page.blocks}
                        className="flex-[1_1_420px]"
                        bodyClassName="py-2"
                    >
                        <Blocks steps={steps} selected={selected} onSelect={select} />
                    </Section>
                )}
                <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-5">
                    <Section title={LABELS.pipelines.page.triggers} bodyClassName="py-2">
                        <Triggers
                            schedules={schedules.value?.items ?? null}
                            steps={steps}
                            sources={(listening.value?.items ?? []).map((row) => fresher[row.code] ?? row)}
                            document={pipeline.document}
                            onSourceChanged={(row) => {
                                setFresher((current) => ({ ...current, [row.code]: row }))
                            }}
                        />
                    </Section>
                    <Section title={LABELS.pipelines.page.connections} bodyClassName="py-2">
                        <Reaches
                            codes={connectionsNamed(pipeline.document)}
                            held={held.value?.items ?? null}
                        />
                    </Section>
                </div>
            </div>

            <RunDialog
                open={running}
                pipeline={pipeline}
                document={pipeline.document}
                username={auth.identity?.username ?? null}
                warnings={[]}
                onOpenChange={setRunning}
                onStarted={(accepted) => {
                    if (accepted.run_id === null) {
                        toast.warning(
                            accepted.detail ?? LABELS.editor.topbar.nothing_started(accepted.status),
                        )
                        return
                    }
                    void navigate(`/runs/${accepted.run_id}`)
                }}
            />
        </div>
    )
}

/** Under the graph: the chosen box's block, what it waits for and what it feeds. */
function ChosenStep({ steps, code }: { steps: readonly StepShape[]; code: string }) {
    const step = steps.find((one) => one.code === code)
    if (step === undefined) return null
    const feeds = steps.filter((one) => one.depends_on.includes(code)).map((one) => one.code)
    return (
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1.5 border-t border-border px-5 py-3 text-sm">
            <InlineCode value={step.code} className="font-medium" tone="neutral" bare size="sm" />
            <InlineCode value={step.block} tone="muted" bare size="xs" />
            {step.depends_on.length > 0 && (
                <span className="min-w-0">
                    <span className="text-muted-foreground">{LABELS.pipelines.page.after} </span>
                    <InlineCode value={step.depends_on.join(', ')} tone="neutral" bare size="xs" />
                </span>
            )}
            {feeds.length > 0 && (
                <span className="min-w-0">
                    <span className="text-muted-foreground">{LABELS.pipelines.page.feeds} </span>
                    <InlineCode value={feeds.join(', ')} tone="neutral" bare size="xs" />
                </span>
            )}
        </div>
    )
}

/** Which block each step runs: one row per block, its steps as chips that choose them. */
function Blocks({
    steps,
    selected,
    onSelect,
}: {
    steps: readonly StepShape[]
    selected: string | null
    onSelect: (step: string) => void
}) {
    const byBlock = useMemo(() => {
        const grouped = new Map<string, string[]>()
        for (const step of steps) {
            if (step.kind !== 'block') continue
            grouped.set(step.block, [...(grouped.get(step.block) ?? []), step.code])
        }
        return [...grouped.entries()]
    }, [steps])
    return (
        <div>
            {byBlock.map(([block, codes]) => (
                <div
                    key={block}
                    className="flex flex-wrap items-baseline gap-x-3.5 gap-y-1.5 border-t border-border py-2.5 first:border-t-0"
                >
                    <InlineCode
                        value={block}
                        className="w-48 shrink-0 font-medium"
                        tone="neutral"
                        bare
                        size="xs"
                    />
                    <span className="flex min-w-0 flex-[1_1_160px] flex-wrap gap-1">
                        {codes.map((code) => (
                            <button
                                key={code}
                                type="button"
                                className={cn(
                                    'h-6 max-w-full truncate rounded-sm bg-secondary px-1.5 font-mono text-xs outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring',
                                    code === selected && 'ring-2 ring-foreground',
                                )}
                                title={LABELS.pipelines.page.choose_step(code)}
                                aria-pressed={code === selected}
                                onClick={() => {
                                    onSelect(code)
                                }}
                            >
                                {code}
                            </button>
                        ))}
                    </span>
                </div>
            ))}
        </div>
    )
}

/**
 * What fires the pipeline: its schedules, and the sources its steps listen on. A source a request
 * reaches says where it is called and how, with the verb that replaces its credential.
 */
function Triggers({
    schedules,
    steps,
    sources: held,
    document,
    onSourceChanged,
}: {
    schedules: ScheduleOut[] | null
    steps: readonly StepShape[]
    sources: readonly SourceOut[]
    document: JsonMap | null
    onSourceChanged: (row: SourceOut) => void
}) {
    const sources = steps.filter((step) => step.kind === 'source')
    if (schedules === null) return null
    if (schedules.length === 0 && sources.length === 0)
        return <p className="text-sm text-muted-foreground">{LABELS.pipelines.page.no_triggers}</p>
    return (
        <div>
            {schedules.map((schedule) => {
                const clock = clockOf(schedule)
                const next = nextFireView(schedule)
                return (
                    <Link
                        key={schedule.id}
                        to="/triggers"
                        className="-mx-2 flex items-center gap-3 rounded-md px-2 py-2 text-sm hover:bg-muted"
                    >
                        <ICONS.schedule className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                        <InlineCode value={schedule.code} tone="neutral" bare size="xs" />
                        <span
                            className={cn(
                                'min-w-0 flex-1 truncate text-muted-foreground',
                                clock.mono && 'font-mono text-xs',
                            )}
                        >
                            {clock.text}
                        </span>
                        {next.kind === 'due' && (
                            <Instant at={next.at} className="text-xs text-muted-foreground" />
                        )}
                        {next.kind === 'paused' && (
                            <span className="text-xs text-muted-foreground">{LABELS.state.armed.paused}</span>
                        )}
                    </Link>
                )
            })}
            {sources.map((step) => {
                const row = held.find((one) => one.code === step.code)
                const auth = row === undefined ? null : authLine(row)
                return (
                    <div key={step.code} className="space-y-1.5 py-2" data-testid="pipeline-source">
                        <div className="flex items-center gap-3 text-sm">
                            <ICONS.source className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                            <InlineCode value={step.code} tone="neutral" bare size="xs" />
                            <span className="min-w-0 truncate text-muted-foreground">
                                {LABELS.pipelines.page.listens(step.block)}
                            </span>
                        </div>
                        {row !== undefined && <EndpointAddress source={row} />}
                        {row !== undefined && auth !== null && (
                            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
                                <span className="min-w-0 text-sm text-muted-foreground">{auth}</span>
                                <NewToken
                                    source={row}
                                    body={sampleBody(document, step.code)}
                                    onReplaced={onSourceChanged}
                                />
                            </div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}

/** What the pipeline reaches: each connection it names, and how that one is. */
function Reaches({ codes, held }: { codes: readonly string[]; held: readonly ConnectionOut[] | null }) {
    if (codes.length === 0)
        return <p className="text-sm text-muted-foreground">{LABELS.pipelines.page.no_connections}</p>
    const byCode = new Map((held ?? []).map((row) => [row.code, row]))
    return (
        <div>
            {codes.map((code) => {
                const row = byCode.get(code)
                return (
                    <Link
                        key={code}
                        to={`/connections/${encodeURIComponent(code)}`}
                        className="-mx-2 flex items-center gap-3 rounded-md px-2 py-2 hover:bg-muted"
                    >
                        <span className="flex min-w-0 flex-1 flex-col">
                            {row !== undefined && row.name !== null && (
                                <span className="truncate text-sm font-medium">{row.name}</span>
                            )}
                            <InlineCode value={code} tone="muted" bare size="xs" />
                        </span>
                        {row !== undefined && <InlineCode value={row.kind} tone="muted" bare size="xs" />}
                        {row !== undefined && <HealthSaid view={healthOf(row)} />}
                    </Link>
                )
            })}
        </div>
    )
}
