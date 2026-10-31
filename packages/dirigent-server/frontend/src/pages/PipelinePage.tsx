import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import { Breadcrumb } from '@/components/Breadcrumb'
import { HealthSaid } from '@/components/connections/Health'
import { Code } from '@/components/ds/Code'
import { Panel } from '@/components/ds/Panel'
import { Instant } from '@/components/Instant'
import { Markdown } from '@/components/Markdown'
import { PageState } from '@/components/PageState'
import { RunDialog } from '@/components/pipeline/RunDialog'
import { ShapeGraph } from '@/components/pipeline/ShapeGraph'
import { TagChips } from '@/components/TagChips'
import { ToolbarActions } from '@/components/ToolbarActions'
import { useMayWrite } from '@/hooks/use-may-write'
import { useRead } from '@/hooks/use-read'
import { useStore } from '@/hooks/use-store'
import { authStore } from '@/lib/auth'
import { healthOf, readConnections, type ConnectionOut } from '@/lib/connections'
import { titleOf } from '@/lib/identity'
import { ICONS } from '@/lib/icons'
import { counted, LABELS } from '@/lib/labels'
import { applyPipeline, readPipeline, type StepShape } from '@/lib/pipelines'
import { connectionsNamed } from '@/lib/requirements'
import { sayRefusal } from '@/components/Refusal'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { clockOf, nextFireView, readSchedules, type ScheduleOut } from '@/lib/triggers'
import { cn } from '@/lib/utils'

/** The address of a pipeline's editor. */
export function editorPath(code: string): string {
    return `/pipelines/${encodeURIComponent(code)}/edit`
}

/**
 * One pipeline, led by its graph.
 *
 * THE GRAPH FIRST, THEN WHAT IT RUNS, WHAT FIRES IT AND WHAT IT REACHES. The heading carries the
 * three verbs: Edit opens the editor, Validate dry-runs the stored version against the instance
 * as it is now, and `Run…` asks for what a run needs. Nothing on this page writes the document.
 */
export function PipelinePage() {
    const { code = '' } = useParams()
    const navigate = useNavigate()
    const auth = useStore(authStore)
    const write = useMayWrite()
    const detail = useRead(useCallback(() => readPipeline(code), [code]))
    const schedules = useRead(useCallback(() => readSchedules(code, null), [code]))
    const held = useRead(useCallback(() => readConnections(null), []))
    const [selected, setSelected] = useState<string | null>(null)
    const [running, setRunning] = useState(false)
    const [validating, setValidating] = useState(false)

    const pipeline = detail.value
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
    const noVersion = pipeline.document === null
    return (
        <div className="flex min-w-0 flex-col">
            <Breadcrumb trail={[{ label: LABELS.screen.pipelines.name, to: '/pipelines' }]} />
            <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h1 className="text-page font-medium tracking-tight">{titleOf(pipeline)}</h1>
                    <div className="mt-1.5">
                        <Code value={pipeline.code} />
                    </div>
                </div>
                <ToolbarActions
                    actions={[
                        {
                            id: 'edit',
                            label: LABELS.action.edit,
                            icon: ICONS.edit,
                            onClick: () => {
                                void navigate(editorPath(pipeline.code))
                            },
                        },
                        {
                            id: 'validate',
                            label: LABELS.action.validate,
                            onClick: validate,
                            disabled: !write.may || noVersion || validating,
                            why: write.why ?? (noVersion ? LABELS.editor.canvas.nothing_to_draw : undefined),
                        },
                        {
                            id: 'run',
                            label: LABELS.action.asks(LABELS.action.run),
                            icon: ICONS.run,
                            variant: 'default',
                            onClick: () => {
                                setRunning(true)
                            },
                            disabled: !write.may || noVersion || !pipeline.active,
                            why:
                                write.why ??
                                (noVersion
                                    ? LABELS.editor.topbar.not_applied
                                    : pipeline.active
                                      ? undefined
                                      : LABELS.pipelines.deactivated.explained),
                        },
                    ]}
                />
            </div>

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

            <Panel title={LABELS.pipelines.page.graph} tone="graph" inset={false} className="mt-6">
                {steps.length === 0 ? (
                    <p className="p-4 text-sm text-muted-foreground">
                        {LABELS.editor.canvas.nothing_to_draw}
                    </p>
                ) : (
                    <ShapeGraph steps={steps} selected={selected} onSelect={setSelected} />
                )}
                {selected !== null && <ChosenStep steps={steps} code={selected} />}
            </Panel>

            <div className="mt-5 flex flex-wrap items-start gap-5">
                <Panel title={LABELS.pipelines.page.blocks} className="flex-[1_1_420px]" bodyClassName="py-2">
                    <Blocks steps={steps} selected={selected} onSelect={setSelected} />
                </Panel>
                <div className="flex min-w-0 flex-[1_1_300px] flex-col gap-5">
                    <Panel title={LABELS.pipelines.page.triggers} bodyClassName="py-2">
                        <Triggers schedules={schedules.value?.items ?? null} steps={steps} />
                    </Panel>
                    <Panel title={LABELS.pipelines.page.connections} bodyClassName="py-2">
                        <Reaches
                            codes={connectionsNamed(pipeline.document)}
                            held={held.value?.items ?? null}
                        />
                    </Panel>
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
            <Code value={step.code} tone="body" className="text-sm font-medium" />
            <Code value={step.block} />
            {step.depends_on.length > 0 && (
                <span className="min-w-0">
                    <span className="text-muted-foreground">{LABELS.pipelines.page.after} </span>
                    <Code value={step.depends_on.join(', ')} tone="body" />
                </span>
            )}
            {feeds.length > 0 && (
                <span className="min-w-0">
                    <span className="text-muted-foreground">{LABELS.pipelines.page.feeds} </span>
                    <Code value={feeds.join(', ')} tone="body" />
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
                    <Code value={block} tone="body" className="w-32 shrink-0 font-medium" />
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

/** What fires the pipeline: its schedules, and the sources its steps listen on. */
function Triggers({ schedules, steps }: { schedules: ScheduleOut[] | null; steps: readonly StepShape[] }) {
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
                        <Code value={schedule.code} tone="body" />
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
            {sources.map((step) => (
                <div key={step.code} className="flex items-center gap-3 py-2 text-sm">
                    <ICONS.source className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                    <Code value={step.code} tone="body" />
                    <span className="min-w-0 truncate text-muted-foreground">
                        {LABELS.pipelines.page.listens(step.block)}
                    </span>
                </div>
            ))}
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
                            <Code value={code} />
                        </span>
                        {row !== undefined && <Code value={row.kind} />}
                        {row !== undefined && <HealthSaid view={healthOf(row)} />}
                    </Link>
                )
            })}
        </div>
    )
}
