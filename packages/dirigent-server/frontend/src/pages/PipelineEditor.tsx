import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router'
import { toast } from 'sonner'

import { ApplyDialog } from '@/components/pipeline/ApplyDialog'
import { MintedToken } from '@/components/triggers/Endpoint'
import { PipelineTab } from '@/components/pipeline/PipelineTab'
import { ReportPane } from '@/components/pipeline/ReportPane'
import { RunDialog } from '@/components/pipeline/RunDialog'
import { SourceTab } from '@/components/pipeline/SourceTab'
import { StepTab } from '@/components/pipeline/StepTab'
import { ScreenTrail } from '@/components/ScreenTrail'
import { PageHead } from '@/components/PageHead'
import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { Section } from '@winterop-com/sokkel-ui/Section'
import { PageState } from '@/components/PageState'
import { Toolbar } from '@winterop-com/sokkel-ui/Toolbar'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { readConnections, type ConnectionOut } from '@/lib/connections'
import { ICONS } from '@/lib/icons'
import { readSchemas, type SchemaOut } from '@/lib/schemas'
import { useMayWrite } from '@/hooks/use-may-write'
import { useSmallScreen } from '@/hooks/use-small-screen'
import { useStore } from '@/hooks/use-store'
import { stepKeyFor } from '@/lib/add-step'
import { ApiError, type JsonMap, type Problem } from '@/lib/api'
import { authStore } from '@/lib/auth'
import { catalogUnread, readBlock, readCatalog, type BlockEntry } from '@/lib/blocks'
import { placeStep, type Placement } from '@/lib/canvas-layout'
import { headingOf, titleOf } from '@/lib/identity'
import { shutWith, TOOLBAR_WORDS } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { cycleRefusal, stepNeeds, withEdge, withoutEdge, withoutStep } from '@/lib/graph-edits'
import { fillPanel, openPanelTab, type PanelTab } from '@/lib/panels'
import { askAddStep, askRelayout } from '@/lib/canvas-actions'
import { RUN_GROUP, registerActions } from '@/lib/palette'
import { firstShut } from '@/lib/roles'
import {
    applyVariant,
    blockOf,
    changeDocument,
    documentStore,
    type DocumentEdits,
    editsIn,
    forgetDocument,
    liftedDocument,
    loadDocument,
    NEW_DOCUMENT,
    startDocument,
    stepNames,
    stepTabLabel,
    withDependsOn,
    withoutReport,
    withReport,
    withStep,
    withStepConfig,
    withStepName,
    writeSource,
} from '@/lib/pipeline-document'
import { appliedNote, issuesNote } from '@/lib/pipeline-plan'
import {
    importanceMark,
    importanceOf,
    readDocumentSchema,
    readPipeline,
    readVersions,
    type PipelineDetail,
    type PipelineVersionOut,
} from '@/lib/pipelines'
import { anythingUnmet, unmetIn, unmetLines } from '@/lib/requirements'
import { EVERY_RUN, readRuns, type RunOut } from '@/lib/runs'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import {
    declaredMethods,
    readPipelineSources,
    sampleBody,
    type SourceOut,
    type SourceTokenOut,
} from '@/lib/sources'

/**
 * One pipeline: its document as a graph, the step in front of somebody, and what applying does.
 *
 * THE DOCUMENT IS EDITED LOCALLY AND APPLIED AS A WHOLE. A pipeline is a chain of immutable
 * versions and the only verb that changes one is `$apply`, so this screen holds a local copy in
 * `lib/pipeline-document`, counts what differs from the stored version, and sends the whole
 * document when somebody says so. Nothing here writes a field at a time.
 *
 * THE GRAPH IS THE DOCUMENT, NOT A RUN. It draws `steps` and `depends_on` from the version being
 * edited; a run's graph is its own screen and its own pinned definition.
 *
 * THE SERVER IS THE AUTHORITY ON WHETHER IT APPLIES. The step form refuses what one field's own
 * schema refuses, the source pane squiggles what this instance's composed document schema
 * refuses, and Validate asks the instance itself -- which is the same dry run Apply confirms.
 *
 * A DOCUMENT WITH NO PIPELINE BEHIND IT IS THE SAME SCREEN. `/pipelines/$new` opens it on a
 * skeleton nothing has applied: everything in the document is editable, the code among it,
 * Validate asks the instance what it makes of the draft, and the first apply is what creates
 * the pipeline and takes the reader to the address it will keep.
 *
 * WHAT THIS INSTANCE HAS NOT GOT IS COMPUTED ONCE AND DRAWN FOUR TIMES: a chip in the pipeline
 * pane, a word on a connections row, a mark on the graph node, and the warning in the run
 * dialog. `lib/requirements` is that decision, and it says nothing at all while the catalog and
 * the connections listing are still being read.
 */

/** React Flow is shared with the run screen and is not in the entry chunk. */
const PipelineGraph = lazy(() =>
    import('@/components/pipeline/PipelineGraph').then((module) => ({ default: module.PipelineGraph })),
)

/** The picker over the installed starters, fetched only when the empty canvas asks for it. */
const StarterPicker = lazy(() =>
    import('@/components/examples/StarterPicker').then((module) => ({ default: module.StarterPicker })),
)

/** How many recent runs the pipeline pane carries. */
const RECENT_RUNS = 3

/** How many versions the pipeline pane carries. */
const RECENT_VERSIONS = 5

export function PipelineEditor() {
    // No `:code` at all is the new-document route: this screen with no pipeline behind it.
    const { code: addressed } = useParams()
    const creating = addressed === undefined
    const code = addressed ?? NEW_DOCUMENT
    const navigate = useNavigate()
    // A file picked on the listing arrives as the navigation state, and only matters once.
    const preloaded = (useLocation().state as { document?: string } | null)?.document
    const auth = useStore(authStore)
    const small = useSmallScreen()
    const write = useMayWrite()
    const mayWrite = write.may
    const state = useStore(documentStore)

    // Keyed by the pipeline it is of, so opening another one shows its loading card rather than
    // the last one's document for a frame. Nothing here is cleared from inside an effect.
    const [read, setRead] = useState<{ of: string; detail: PipelineDetail | null; problem: Problem | null }>({
        of: '',
        detail: null,
        problem: null,
    })
    const [versions, setVersions] = useState<PipelineVersionOut[]>([])
    const [connections, setConnections] = useState<ConnectionOut[] | null>(null)
    const [schemas, setSchemas] = useState<SchemaOut[] | null>(null)
    const [runs, setRuns] = useState<RunOut[]>([])
    // What the instance holds of the document's sources, which is where a source step's URL is read.
    const [sources, setSources] = useState<SourceOut[]>([])
    const [blocks, setBlocks] = useState<BlockEntry[]>([])
    const [schema, setSchema] = useState<JsonMap | null>(null)
    const [selected, setSelected] = useState<string | null>(null)
    // Keyed by the block it was read for, for the same reason the pipeline read is.
    const [step, setStep] = useState<{
        of: string | null
        block: BlockEntry | null
        problem: Problem | null
    }>({
        of: null,
        block: null,
        problem: null,
    })
    const [dialog, setDialog] = useState<'none' | 'apply' | 'validate' | 'run'>('none')
    // The tokens the last apply created, and where the screen goes once each has been read.
    const [minted, setMinted] = useState<{ tokens: SourceTokenOut[]; after: string | null }>({
        tokens: [],
        after: null,
    })
    const [issues, setIssues] = useState<string | null>(null)
    const [picking, setPicking] = useState(false)

    const local = state.code === code ? state.local : null
    const source = state.code === code ? state.source : null
    const edits = useMemo(() => editsIn(state.applied, local), [state.applied, local])
    // A BOX IS MARKED AGAINST A VERSION, so a document nothing has applied marks none of them.
    // Every step of a draft differs from nothing at all, and a canvas where each one said
    // "edited" would be saying it of the word rather than of the step.
    const marks = useMemo<DocumentEdits>(
        () => (state.applied === null ? { ...edits, steps: [] } : edits),
        [edits, state.applied],
    )

    useEffect(() => {
        // There is no pipeline to read. A blank document opens on the step tab like any other:
        // the canvas says how to add the first step, and the source, whose schema would mark
        // the empty steps map before anything has been done, is a tab away. A document that
        // arrived with content, picked from a file, opens on the source that holds it.
        if (creating) {
            startDocument(preloaded)
            openPanelTab(preloaded === undefined ? 'step' : 'source')
            return
        }
        let cancelled = false
        void readPipeline(code).then(
            (detail) => {
                if (cancelled) return
                setRead({ of: code, detail, problem: null })
                loadDocument(code, detail.document)
            },
            (error: unknown) => {
                if (cancelled) return
                setRead({ of: code, detail: null, problem: error instanceof ApiError ? error.problem : null })
            },
        )
        return () => {
            cancelled = true
        }
        // preloaded matters only on the first render of the new screen; navigation state does not change under it.
        // oxlint-disable-next-line react/exhaustive-effect-dependencies
    }, [code, creating, preloaded])

    const pipeline = read.of === code ? read.detail : null
    const problem = read.of === code ? read.problem : null

    useEffect(() => forgetDocument, [])

    // Everything the pipeline pane says about the instance rather than about the document. Each
    // is optional: a refusal leaves that section saying it could not be read, not the screen.
    useEffect(() => {
        let cancelled = false
        const settle = <T,>(reading: Promise<T>, keep: (value: T) => void) => {
            void reading.then(
                (value) => {
                    if (!cancelled) keep(value)
                },
                () => {
                    // This instance would not answer for it. The pane says so where it belongs.
                },
            )
        }
        // Neither is a question about a pipeline that does not exist yet.
        if (!creating) {
            settle(readVersions(code, RECENT_VERSIONS), (page) => {
                setVersions(page.items)
            })
            settle(readRuns({ ...EVERY_RUN, pipeline: code }, null, RECENT_RUNS), (page) => {
                setRuns(page.items)
            })
            settle(readPipelineSources(code), (page) => {
                setSources(page.items)
            })
        }
        settle(readConnections(), (page) => {
            setConnections(page.items)
        })
        settle(readSchemas(), (page) => {
            setSchemas(page.items)
        })
        settle(readCatalog(), (catalog) => {
            setBlocks(catalog.blocks)
        })
        settle(readDocumentSchema(), setSchema)
        return () => {
            cancelled = true
        }
    }, [code, creating])

    // The chosen step's block, which is what its form is generated from.
    const chosenBlock = selected === null ? null : blockOf(local, selected)
    useEffect(() => {
        if (chosenBlock === null) return
        let cancelled = false
        void readBlock(chosenBlock).then(
            (entry) => {
                if (!cancelled) setStep({ of: chosenBlock, block: entry, problem: null })
            },
            (error: unknown) => {
                if (cancelled) return
                setStep({
                    of: chosenBlock,
                    block: null,
                    problem: error instanceof ApiError ? error.problem : null,
                })
            },
        )
        return () => {
            cancelled = true
        }
    }, [chosenBlock])

    // A read for another block is a read of nothing yet, and the panel says so rather than
    // showing the last step's schema under this step's name.
    const stepRead = useMemo(
        () => (step.of === chosenBlock ? step : { of: chosenBlock, block: null, problem: null }),
        [chosenBlock, step],
    )

    const steps = stepNames(local)
    const applied = versions[0] ?? null

    // Two reads that may not have landed, and null until each does: an unread catalog is not an
    // empty one, and a screen that shouted "not installed" for the half second before it lands
    // would teach a reader to stop believing it.
    const catalog = useMemo(() => (catalogUnread(blocks) ? null : blocks.map((block) => block.id)), [blocks])
    const held = useMemo(() => connections?.map((one) => one.code) ?? null, [connections])
    const stored = useMemo(() => schemas?.map((one) => one.code) ?? null, [schemas])
    const unmet = useMemo(() => unmetIn(local, catalog, held, stored), [catalog, held, local, stored])
    const warnings = useMemo(() => unmetLines(unmet), [unmet])

    // THE NOTE IS STATEFUL OR IT IS NOT THERE. What the graph already draws is not restated
    // along the foot; what the bar carries is what is wrong with the document and nothing else.
    //
    // THE IDENTIFIER IS A STANDING FACT: which version the instance holds, and nothing about the
    // apply that wrote it. An apply is an event and is announced once, as it happens, and who
    // made it is in the Versions section of the pipeline's own pane.
    useEffect(() => {
        const missing = anythingUnmet(unmet) ? LABELS.editor.topbar.unmet_here(warnings.length) : null
        const said = [missing, issues].filter((part) => part !== null)
        setScreenStatus({
            note: said.length === 0 ? null : said.join(' · '),
            tone: said.length === 0 ? 'quiet' : 'warn',
            identifier:
                applied === null
                    ? LABELS.editor.version.none
                    : LABELS.editor.version.short(String(applied.version)),
        })
        return clearScreenStatus
    }, [applied, issues, unmet, warnings.length])

    // AN EDGE IS A `depends_on` ENTRY, so drawing one on the canvas and choosing one from the
    // chips in the step's pane are the same edit against the same local document.
    const connect = useCallback(
        (from: string, to: string) => {
            const refused = cycleRefusal(stepNeeds(local), from, to)
            if (refused !== null) {
                toast.warning(refused)
                return
            }
            changeDocument((current) => withEdge(current, from, to))
        },
        [local],
    )

    const refuse = useCallback((reason: string) => {
        toast.warning(reason)
    }, [])

    const disconnect = useCallback((from: string, to: string) => {
        changeDocument((current) => withoutEdge(current, from, to))
    }, [])

    // A DELETED STEP IS NO LONGER SOMETHING TO READ, so the panel's step tab lets go of it as
    // the document does.
    const removeStep = useCallback((key: string) => {
        changeDocument((current) => withoutStep(current, key))
        setSelected((chosen) => (chosen === key ? null : chosen))
    }, [])

    /**
     * One more step, running the block the menu was answered with.
     *
     * THE KEY IS DERIVED RATHER THAN ASKED FOR. A menu places a step on one keystroke, so the
     * block's own name is the key and the document's own keys are what makes it unique; the
     * step's pane is where it is renamed, alongside everything else about it.
     */
    const addStep = (block: string, after: string | null, at: Placement | null) => {
        const added = stepKeyFor(block, steps)
        const written = changeDocument((current) => {
            const grown = withStep(current, added, block)
            return after === null ? grown : withEdge(grown, after, added)
        })
        if (!written) return
        // A step dropped somewhere stays where it was dropped; one added from the pointer or the
        // corner takes elk's suggestion, like every step nobody has moved.
        if (at !== null) placeStep(added, at)
        setSelected(added)
        openPanelTab('step')
    }

    // WHAT DOES NOT PARSE IS NOT A DOCUMENT TO ACT ON. While the source pane holds text that is
    // not one, the local document is the last that parsed -- so the step form, and the three
    // verbs along the top that would send that stale document, are all shut with one sentence.
    const disabled = small
        ? LABELS.editor.topbar.read_only
        : state.parseError === null
          ? undefined
          : LABELS.editor.topbar.unparsed

    // Editing the local document writes nothing, so what a role shuts is only what would reach
    // the server: the three verbs along the top, and not the form below them.
    const sent = firstShut(write.why, disabled)

    // `$run` runs the version the instance holds, and there is not one yet.
    const runRefusal = creating ? firstShut(write.why, LABELS.editor.topbar.not_applied) : sent

    // A DIALOG IS A DECISION, AND THIS ONE WOULD HAVE NONE TO MAKE. An apply of the version the
    // instance already holds writes nothing, so the verb is shut here rather than opening a
    // dialog whose own answer is that pressing its button would do nothing. Validate and Run are
    // unaffected: both act on a document that has not changed.
    const applyRefusal = firstShut(
        sent,
        creating || edits.count > 0 ? undefined : LABELS.editor.apply.nothing_to_apply,
    )

    // The palette's own shelf, named for the pipeline the way every other reading of it is.
    const shelf = LABELS.editor.topbar.shelf(
        RUN_GROUP,
        creating ? LABELS.editor.topbar.new_pipeline : pipeline === null ? code : titleOf(pipeline),
    )

    useEffect(() => {
        return registerActions([
            // A row that would open a dialog about a pipeline this instance has not got, or one
            // this account's role would be refused, is a row the palette does not offer.
            ...(mayWrite && !small
                ? [
                      {
                          id: 'pipeline:validate',
                          title: LABELS.editor.apply.validate_title,
                          group: shelf,
                          screen: true,
                          icon: ICONS.validate,
                          keywords: ['check', 'dry run', 'plan'],
                          run: () => {
                              setDialog('validate')
                          },
                      },
                      {
                          id: 'pipeline:apply',
                          title: LABELS.editor.apply.title,
                          group: shelf,
                          screen: true,
                          icon: ICONS.apply,
                          keywords: ['write', 'version', 'save'],
                          run: () => {
                              if (applyRefusal === undefined) setDialog('apply')
                              else toast.info(applyRefusal)
                          },
                      },
                  ]
                : []),
            ...(creating || !mayWrite || small
                ? []
                : [
                      {
                          id: 'pipeline:run',
                          title: LABELS.editor.topbar.run_pipeline,
                          group: shelf,
                          screen: true,
                          icon: ICONS.run,
                          keywords: ['start', 'adhoc'],
                          run: () => {
                              setDialog('run')
                          },
                      },
                  ]),
            ...(small
                ? []
                : [
                      {
                          id: 'pipeline:add-step',
                          title: LABELS.action.asks(LABELS.editor.canvas.add_step),
                          group: shelf,
                          screen: true,
                          icon: ICONS.create,
                          keywords: ['block', 'new', 'insert'],
                          run: askAddStep,
                      },
                  ]),
            {
                id: 'pipeline:relayout',
                title: LABELS.editor.topbar.relayout,
                group: shelf,
                screen: true,
                icon: ICONS.relayout,
                keywords: ['tidy', 'arrange', 'elk'],
                run: askRelayout,
            },
        ])
    }, [applyRefusal, creating, mayWrite, shelf, small])

    const tabs = useMemo<PanelTab[]>(() => {
        if (local === null && pipeline === null) return []
        return [
            {
                id: 'step',
                // The tab carries the selection, so the strip says what the panel is about
                // without the pane having to repeat it.
                label: stepTabLabel(selected),
                render: () =>
                    selected === null || local === null ? (
                        <p className="p-4 text-sm text-muted-foreground">{LABELS.editor.step.none_chosen}</p>
                    ) : (
                        <StepTab
                            key={selected}
                            step={selected}
                            document={local}
                            source={sources.find((row) => row.code === selected) ?? null}
                            onSourceChanged={(row) => {
                                setSources((rows) => rows.map((one) => (one.code === row.code ? row : one)))
                            }}
                            block={stepRead.block}
                            blockProblem={stepRead.problem}
                            schemas={schemas}
                            connections={connections}
                            disabled={disabled}
                            onConfig={(config) => {
                                changeDocument((current) => withStepConfig(current, selected, config))
                            }}
                            onDependsOn={(names) => {
                                changeDocument((current) => withDependsOn(current, selected, names))
                            }}
                            onName={(given) => {
                                changeDocument((current) => withStepName(current, selected, given))
                            }}
                        />
                    ),
            },
            // There is no pipeline to read until one has been applied.
            ...(pipeline === null
                ? []
                : [
                      {
                          id: 'pipeline',
                          label: LABELS.word.pipeline.label,
                          render: () => (
                              <PipelineTab
                                  pipeline={pipeline}
                                  document={local}
                                  versions={versions}
                                  connections={connections}
                                  runs={runs}
                                  unmet={unmet}
                              />
                          ),
                      },
                  ]),
            {
                id: 'report',
                label: LABELS.word.report,
                render: () => (
                    <ReportPane
                        document={local}
                        disabled={disabled}
                        onChange={(chosen, template) => {
                            changeDocument((current) =>
                                chosen === 'none'
                                    ? withoutReport(current)
                                    : withReport(current, chosen === 'own' ? template : null),
                            )
                        }}
                    />
                ),
            },
            {
                id: 'source',
                label: LABELS.word.source,
                render: () => (
                    <SourceTab
                        document={local}
                        source={source}
                        schema={schema}
                        parseError={state.parseError}
                        readOnly={small}
                        onWrite={writeSource}
                    />
                ),
            },
        ]
    }, [
        connections,
        disabled,
        local,
        pipeline,
        runs,
        schema,
        schemas,
        selected,
        small,
        source,
        sources,
        state.parseError,
        stepRead,
        unmet,
        versions,
    ])

    useEffect(
        () =>
            fillPanel(tabs, {
                screen: `editor:${code}`,
                open: creating && preloaded !== undefined ? 'source' : 'step',
            }),
        [tabs, code, creating, preloaded],
    )

    if (!creating && pipeline === null) {
        return (
            <PageState loading={problem === null} problem={problem} empty={false}>
                {null}
            </PageState>
        )
    }

    const heading = pipeline === null ? null : headingOf(pipeline)
    // The document on the canvas rather than the row: the mark moves with the edit that moved it.
    const matters = importanceMark(importanceOf(local))

    return (
        <div className="-mb-9 flex min-h-0 flex-1 flex-col gap-3">
            <PageHead>
                <ScreenTrail
                    trail={[
                        { label: LABELS.screen.pipelines.name, href: '/pipelines' },
                        ...(heading === null
                            ? []
                            : [{ label: heading.title, href: `/pipelines/${code}`, code: !heading.named }]),
                    ]}
                />
                <div className="flex min-h-9 items-center">
                    <Toolbar
                        className="flex-1"
                        itemVariant="outline"
                        itemsAlign="end"
                        nowrap
                        wordsOnly
                        words={TOOLBAR_WORDS}
                        items={
                            // NOTHING THAT WRITES, AND NOTHING THAT ASKS THE SERVER ABOUT WHAT CANNOT
                            // BE WRITTEN: below the breakpoint the strip carries the document's
                            // identity and the line saying it is read.
                            small
                                ? undefined
                                : [
                                      {
                                          id: 'validate',
                                          label: LABELS.action.validate,
                                          icon: <ICONS.validate aria-hidden />,
                                          ...shutWith(sent !== undefined, sent),
                                          onSelect: () => {
                                              setDialog('validate')
                                          },
                                      },
                                      {
                                          id: 'run',
                                          label: LABELS.action.asks(LABELS.action.run),
                                          icon: <ICONS.run aria-hidden />,
                                          ...shutWith(runRefusal !== undefined, runRefusal),
                                          onSelect: () => {
                                              setDialog('run')
                                          },
                                      },
                                  ]
                        }
                        primary={
                            small
                                ? undefined
                                : {
                                      id: 'apply',
                                      variant: applyVariant(edits, creating),
                                      label: LABELS.action.apply,
                                      icon: <ICONS.apply aria-hidden />,
                                      ...shutWith(applyRefusal !== undefined, applyRefusal),
                                      onSelect: () => {
                                          setDialog('apply')
                                      },
                                  }
                        }
                        end={
                            small ? (
                                <span className="shrink-0 text-xs text-muted-foreground">
                                    {LABELS.editor.topbar.read_only}
                                </span>
                            ) : undefined
                        }
                    >
                        {heading === null ? (
                            <span className="shrink-0 text-sm font-medium">
                                {LABELS.editor.topbar.new_pipeline}
                            </span>
                        ) : (
                            <InlineCode value={heading.code ?? code} tone="neutral" bare size="xs" />
                        )}
                        {/* Hidden below the breakpoint, where the strip has only the room for the
                    document's identity and the line saying it is read. */}
                        {matters !== null && (
                            <Chip tone="critical" title={matters.title} className="hidden md:inline-flex">
                                {matters.label}
                            </Chip>
                        )}
                    </Toolbar>
                </div>
            </PageHead>

            <Section
                title={LABELS.pipelines.page.graph}
                flush
                className="mt-3 flex min-h-96 flex-1 flex-col"
                bodyClassName="relative min-h-0 flex-1"
            >
                {local === null ? (
                    <div className="graph-words flex flex-col items-start gap-3 p-4">
                        <p className="text-muted-foreground">{LABELS.editor.canvas.nothing_to_draw}</p>
                    </div>
                ) : (
                    <Suspense
                        fallback={
                            <PageState loading problem={null} empty={false}>
                                {null}
                            </PageState>
                        }
                    >
                        <PipelineGraph
                            pipeline={code}
                            document={local}
                            blocks={blocks}
                            edits={marks}
                            unmet={unmet}
                            selected={selected}
                            // CHOOSING A BOX IS ASKING TO READ IT, so the panel opens on the
                            // step's own tab rather than on whichever one was last in front of
                            // somebody.
                            onSelect={(chosen) => {
                                setSelected(chosen)
                                if (chosen !== null) openPanelTab('step')
                            }}
                            onAddStep={addStep}
                            onConnect={connect}
                            onDisconnect={disconnect}
                            onRemoveStep={removeStep}
                            onRefuse={refuse}
                            emptyAction={
                                // Copying a shipped document is a door nothing else here shows.
                                creating && !small && mayWrite ? (
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => {
                                            setPicking(true)
                                        }}
                                    >
                                        <ICONS.example aria-hidden />
                                        {LABELS.editor.canvas.from_starter}
                                    </Button>
                                ) : undefined
                            }
                            readOnly={small}
                        />
                    </Suspense>
                )}
            </Section>

            {picking && (
                <Suspense fallback={null}>
                    <StarterPicker
                        open
                        onOpenChange={setPicking}
                        onChoose={(document) => {
                            startDocument(document)
                            openPanelTab('source')
                        }}
                    />
                </Suspense>
            )}

            {minted.tokens[0] !== undefined && (
                <MintedToken
                    key={minted.tokens[0].source_id}
                    token={minted.tokens[0]}
                    methods={declaredMethods(local, minted.tokens[0].code)}
                    body={sampleBody(local, minted.tokens[0].code)}
                    onClose={() => {
                        const rest = minted.tokens.slice(1)
                        setMinted({ tokens: rest, after: minted.after })
                        if (rest.length === 0 && minted.after !== null) void navigate(minted.after)
                    }}
                />
            )}

            {local !== null && (
                <ApplyDialog
                    open={dialog === 'apply' || dialog === 'validate'}
                    mode={dialog === 'validate' ? 'validate' : 'apply'}
                    document={local}
                    onOpenChange={(open) => {
                        if (!open) setDialog('none')
                    }}
                    onPlan={(plan) => {
                        setIssues(issuesNote(plan.issues))
                    }}
                    onLift={liftedDocument}
                    onApplied={(result) => {
                        setIssues(issuesNote(result.plan.issues))
                        const note = appliedNote(result)
                        toast.success(note.line, { description: note.detail })
                        const address = creating
                            ? `/pipelines/${encodeURIComponent(result.plan.code)}/edit`
                            : null
                        const { tokens } = result.sources
                        setMinted({ tokens, after: address })
                        if (tokens.length > 0 && address !== null) return
                        // The document has an address of its own now, and it is not this one.
                        if (address !== null) {
                            void navigate(address)
                            return
                        }
                        void readPipeline(code).then(
                            (detail) => {
                                setRead({ of: code, detail, problem: null })
                                loadDocument(code, detail.document)
                            },
                            () => {
                                // The apply landed; the re-read did not. The next reload has it.
                            },
                        )
                        void readVersions(code, RECENT_VERSIONS).then(
                            (page) => {
                                setVersions(page.items)
                            },
                            () => {
                                // The version row keeps what it had.
                            },
                        )
                        void readPipelineSources(code).then(
                            (page) => {
                                setSources(page.items)
                            },
                            () => {
                                // The source rows keep what they had.
                            },
                        )
                    }}
                />
            )}

            {pipeline !== null && (
                <RunDialog
                    open={dialog === 'run'}
                    pipeline={pipeline}
                    document={state.applied}
                    username={auth.identity?.username ?? null}
                    warnings={warnings}
                    onOpenChange={(open) => {
                        if (!open) setDialog('none')
                    }}
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
            )}
        </div>
    )
}
