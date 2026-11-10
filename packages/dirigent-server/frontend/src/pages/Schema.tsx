import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { Description } from '@/components/Description'
import { Section } from '@/components/run/Panel'
import { Field } from '@winterop-com/sokkel-ui/Field'
import { Callout } from '@winterop-com/sokkel-ui/Callout'
import { PageHeader } from '@/components/ds/PageHeader'
import { shutWith } from '@/lib/design-system'
import { Section as LibrarySection } from '@winterop-com/sokkel-ui/Section'
import { PageState } from '@/components/PageState'
import { CodePane } from '@/components/pipeline/CodePane'
import { Refusal } from '@/components/Refusal'
import { WindowButton, WindowedPane } from '@/components/WindowedPane'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { Dialog, DialogContent, DialogTitle } from '@winterop-com/sokkel-ui/primitives/dialog'
import { Input } from '@winterop-com/sokkel-ui/primitives/input'
import { Textarea } from '@winterop-com/sokkel-ui/primitives/textarea'
import { useMayWrite } from '@/hooks/use-may-write'
import { useRead } from '@/hooks/use-read'
import { useSchemaSave } from '@/hooks/use-schema-save'
import type { Problem } from '@/lib/api'
import { headingOf } from '@/lib/identity'
import { counted, LABELS } from '@/lib/labels'
import { refusalOf } from '@/lib/refusal'
import {
    checkInput,
    checkSchema,
    holdsStored,
    marksOf,
    pointerLabel,
    readJson,
    sampleOf,
    sampleText,
    shownCheck,
    spanAt,
    spansOf,
    type CheckAnswer,
    type CheckShown,
    type SchemaViolation,
} from '@/lib/schema-check'
import {
    bodyText,
    deleteSchema,
    draftOf,
    holdDraft,
    readSchema,
    schemaPatch,
    updateSchema,
    whyKept,
    type SchemaOut,
} from '@/lib/schemas'
import { fillPanel } from '@/lib/panels'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'

/** The media type that asks for the meta-schema of the draft the server validates with. */
const SCHEMA_MEDIA_TYPE = 'application/schema+json'

/** How long typing has to pause before the two texts are checked. */
const SETTLE_MS = 350

/**
 * One stored schema: its name, its description, the pipelines that check against it, and the
 * schema itself in the editor it is corrected in; trying a value against it is a window of its
 * own.
 *
 * THE PAGE IS THE SCHEMA. The body has the whole page, as a pipeline's document has its
 * editor; the name, the description and the pipelines that check against it are the right
 * panel's Details, as a pipeline's are. All three are what `SchemaUpdate` carries, and one Save
 * sends what changed. The code is fixed: the route addresses the schema by it, so it is the
 * heading and never a box.
 *
 * TRYING A VALUE IS A WINDOW. `Try a value` opens the schema beside a value and what checking
 * the one against the other found, as large as the screen allows. The check is a run's:
 * `POST /schemas/$check` evaluates the value the way a `validate.schema` step does, against the
 * text in the schema editor rather than what is stored, so a shape is tried before it is saved.
 * The window's schema editor names the page's buffer, so what is typed in either is what the
 * other shows, and the value is kept between one opening and the next.
 *
 * TEXT THAT IS NOT JSON IS SAID WHERE IT WAS TYPED, and nothing is asked of the server for it.
 * EVERY FAILURE IS MARKED WHERE IT IS: a mark on the value at the place its pointer names, and
 * pressing one in the list selects that place.
 */
export function Schema() {
    const { code = '' } = useParams()
    const ask = useCallback(() => readSchema(code), [code])
    const read = useRead(ask)
    const [fresher, setFresher] = useState<SchemaOut | null>(null)
    const schema = fresher !== null && fresher.code === code ? fresher : read.value

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [])

    return (
        <>
            {schema === null && (
                <PageHeader title={code} trail={[{ label: LABELS.screen.schemas.name, to: '/schemas' }]} />
            )}
            <PageState
                loading={schema === null && read.problem === null}
                problem={read.problem}
                empty={false}
            >
                {schema !== null && <SchemaPage key={schema.code} schema={schema} onSaved={setFresher} />}
            </PageState>
        </>
    )
}

function SchemaPage({ schema, onSaved }: { schema: SchemaOut; onSaved: (row: SchemaOut) => void }) {
    const navigate = useNavigate()
    const stored = useMemo(() => bodyText(schema), [schema])
    const [text, setText] = useState(() => draftOf(schema.code, stored))
    const [named, setNamed] = useState(schema.name ?? '')
    const [description, setDescription] = useState(schema.description ?? '')
    const [value, setValue] = useState(() => {
        const opened = readJson(text)
        return sampleText(opened.ok ? opened.value : null)
    })
    const [answer, setAnswer] = useState<CheckAnswer | null>(null)
    const [reveal, setReveal] = useState<{ start: number; end: number } | null>(null)
    const [trying, setTrying] = useState(false)
    const [windowed, setWindowed] = useState(false)
    const [removing, setRemoving] = useState(false)
    const { save, busy, problem, setProblem } = useSchemaSave(schema, onSaved)
    const write = useMayWrite('admin')
    const heading = headingOf(schema)

    const input = useMemo(() => checkInput(text, value), [text, value])
    const shown = shownCheck(input, answer, text, value)

    // Nothing is checked while the window is shut: there is no value on the page to check.
    useEffect(() => {
        if (!trying || input.kind !== 'ready') return
        let live = true
        const timer = setTimeout(() => {
            void checkSchema(input.body, input.value).then(
                (check) => {
                    if (live) setAnswer({ kind: 'checked', check, schema: text, value })
                },
                (error: unknown) => {
                    if (live) setAnswer({ kind: 'refused', problem: refusalOf(error), schema: text, value })
                },
            )
        }, SETTLE_MS)
        return () => {
            live = false
            clearTimeout(timer)
        }
    }, [input, text, trying, value])

    const sample = useMemo(() => {
        const parsed = readJson(text)
        return parsed.ok ? sampleOf(parsed.value) : undefined
    }, [text])

    const errors = shown.kind === 'checked' && shown.current ? shown.check.errors : null
    const marks = useMemo(() => (errors === null ? [] : marksOf(value, errors)), [errors, value])

    const show = (error: SchemaViolation) => {
        const span = spanAt(spansOf(value), error.at)
        if (span !== null) setReveal({ start: span.start, end: span.end })
    }

    const edited = (next: string) => {
        setText(next)
        holdDraft(schema.code, next, stored)
    }

    const unchanged =
        holdsStored(text, schema.body) &&
        given(named) === schema.name &&
        given(description) === schema.description
    const saveWhy = write.why ?? (unchanged ? LABELS.schemas.tester.unchanged : undefined)
    const kept = write.may ? whyKept(schema) : undefined
    const deleteWhy = write.why ?? kept

    const send = () => {
        save(given(named), given(description), text)
    }

    const remove = () => {
        setRemoving(true)
        setProblem(null)
        void deleteSchema(schema.code)
            .then(
                () => {
                    void navigate('/schemas', { replace: true })
                },
                (error: unknown) => {
                    setProblem(refusalOf(error))
                },
            )
            .finally(() => {
                setRemoving(false)
            })
    }

    const [editingDetails, setEditingDetails] = useState(false)
    const [detailsSaving, setDetailsSaving] = useState(false)
    const [detailsProblem, setDetailsProblem] = useState<Problem | null>(null)
    const storedName = schema.name ?? ''
    const storedDescription = schema.description ?? ''
    const saveDetails = useCallback(() => {
        const payload = schemaPatch(schema, given(named), given(description), undefined)
        if (payload === null) {
            setEditingDetails(false)
            return
        }
        setDetailsSaving(true)
        setDetailsProblem(null)
        void updateSchema(schema.code, payload)
            .then(
                (row) => {
                    onSaved(row)
                    setEditingDetails(false)
                },
                (error: unknown) => {
                    setDetailsProblem(refusalOf(error))
                },
            )
            .finally(() => {
                setDetailsSaving(false)
            })
    }, [description, named, onSaved, schema])
    const cancelDetails = useCallback(() => {
        setNamed(storedName)
        setDescription(storedDescription)
        setDetailsProblem(null)
        setEditingDetails(false)
    }, [storedDescription, storedName])

    const mayWrite = write.may
    const details = useMemo(
        () => (
            <Details
                named={named}
                description={description}
                usedBy={schema.used_by}
                mayWrite={mayWrite}
                editing={editingDetails}
                saving={detailsSaving}
                problem={detailsProblem}
                onNamed={setNamed}
                onDescription={setDescription}
                onEditing={setEditingDetails}
                onCancel={cancelDetails}
                onSave={saveDetails}
            />
        ),
        [
            cancelDetails,
            description,
            detailsProblem,
            detailsSaving,
            editingDetails,
            mayWrite,
            named,
            saveDetails,
            schema.used_by,
        ],
    )

    useEffect(
        () =>
            fillPanel([{ id: 'details', label: LABELS.schemas.details_heading, render: () => details }], {
                screen: `schema:${schema.code}`,
                shut: true,
            }),
        [details, schema.code],
    )

    const schemaPane = (className: string) => (
        <CodePane
            value={text}
            mediaType={SCHEMA_MEDIA_TYPE}
            path={`schemas/${schema.code}`}
            label={LABELS.schemas.editor_label}
            readOnly={!write.may}
            wrap
            className={className}
            onChange={edited}
        />
    )

    return (
        <>
            <PageHeader
                title={heading.title}
                code={schema.code}
                trail={[{ label: LABELS.screen.schemas.name, to: '/schemas' }]}
                items={[
                    {
                        id: 'try',
                        label: LABELS.schemas.try_value,
                        onSelect: () => {
                            setTrying(true)
                        },
                    },
                    {
                        id: 'delete',
                        label: removing ? LABELS.action.delete.busy : LABELS.action.delete.verb,
                        destructive: true,
                        ...shutWith(busy || removing || deleteWhy !== undefined, deleteWhy),
                        onSelect: remove,
                    },
                ]}
                primary={{
                    id: 'save',
                    label: busy ? LABELS.action.save.busy : LABELS.action.save.verb,
                    ...shutWith(busy || saveWhy !== undefined, saveWhy),
                    onSelect: send,
                }}
            />
            <div className="flex min-h-0 flex-1 flex-col gap-3">
                {problem !== null && <Refusal problem={problem} />}
                <LibrarySection
                    title={LABELS.word.schema.label}
                    flush
                    className="flex min-h-96 flex-1 flex-col"
                    bodyClassName="flex min-h-0 flex-1 flex-col"
                    actions={
                        <WindowButton
                            name={LABELS.schemas.window_title(schema.code)}
                            onOpen={() => {
                                setWindowed(true)
                            }}
                        />
                    }
                >
                    <WindowedPane
                        name={LABELS.schemas.window_title(schema.code)}
                        frame="none"
                        button="none"
                        open={windowed}
                        onOpenChange={setWindowed}
                        className="min-h-0 flex-1"
                        windowed={schemaPane('min-h-0 flex-1')}
                    >
                        {schemaPane('min-h-0 flex-1')}
                    </WindowedPane>
                </LibrarySection>
            </div>
            <Dialog open={trying} onOpenChange={setTrying}>
                <DialogContent
                    finalFocus={false}
                    className="flex h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-none flex-col gap-3 sm:max-w-none"
                >
                    <div className="flex flex-wrap items-center gap-2 pr-8">
                        <DialogTitle className="text-sm">{LABELS.schemas.try_title(schema.code)}</DialogTitle>
                        <Button
                            variant="outline"
                            size="sm"
                            className="ml-auto"
                            disabled={sample === undefined}
                            title={sample === undefined ? LABELS.schemas.tester.no_example : undefined}
                            onClick={() => {
                                setValue(JSON.stringify(sample, null, 2))
                            }}
                        >
                            {LABELS.schemas.tester.example}
                        </Button>
                        <Button
                            size="sm"
                            disabled={busy || saveWhy !== undefined}
                            title={saveWhy}
                            onClick={send}
                        >
                            {busy ? LABELS.action.save.busy : LABELS.action.save.verb}
                        </Button>
                    </div>
                    <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,22rem)]">
                        <LibrarySection
                            title={LABELS.word.schema.label}
                            flush
                            className="flex min-h-0 flex-col"
                            bodyClassName="flex min-h-0 flex-1 flex-col"
                        >
                            {schemaPane('min-h-48 flex-1')}
                        </LibrarySection>
                        <LibrarySection
                            title={LABELS.schemas.tester.value_heading}
                            flush
                            className="flex min-h-0 flex-col"
                            bodyClassName="flex min-h-0 flex-1 flex-col"
                        >
                            <CodePane
                                value={value}
                                mediaType="application/json"
                                path={`schemas/${schema.code}/value`}
                                label={LABELS.schemas.tester.value_label}
                                wrap
                                className="min-h-48 flex-1"
                                marks={marks}
                                reveal={reveal}
                                onChange={setValue}
                            />
                        </LibrarySection>
                        <Result shown={shown} onShow={show} />
                    </div>
                </DialogContent>
            </Dialog>
        </>
    )
}

/**
 * The right panel's Details: what the schema is called and for, and who checks against it.
 *
 * IT READS LIKE A PIPELINE'S PANE, and is a form only when asked to be. The name and code are the
 * page's heading, so the pane opens on the rendered description; `Edit` turns the name and the
 * description into boxes, and the pane's own Save stores those two alone, so an edit made here is
 * never left waiting on the page's Save.
 */
function Details({
    named,
    description,
    usedBy,
    mayWrite,
    editing,
    saving,
    problem,
    onNamed,
    onDescription,
    onEditing,
    onCancel,
    onSave,
}: {
    named: string
    description: string
    usedBy: readonly string[]
    mayWrite: boolean
    editing: boolean
    saving: boolean
    problem: Problem | null
    onNamed: (text: string) => void
    onDescription: (text: string) => void
    onEditing: (editing: boolean) => void
    /** Put the name and the description back as they are stored, and stop editing them. */
    onCancel: () => void
    /** Store the name and the description alone, and stop editing them once they are stored. */
    onSave: () => void
}) {
    const toggle = (
        <Button
            variant="ghost"
            size="sm"
            className="shrink-0"
            aria-label={LABELS.schemas.edit_details}
            title={LABELS.schemas.edit_details}
            onClick={() => {
                onEditing(true)
            }}
        >
            {LABELS.action.edit}
        </Button>
    )
    const verbs = (
        <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" disabled={saving} onClick={onCancel}>
                {LABELS.action.cancel}
            </Button>
            <Button size="sm" disabled={saving} onClick={onSave}>
                {saving ? LABELS.action.save.busy : LABELS.action.save.verb}
            </Button>
        </div>
    )
    return (
        <div className="flex flex-col gap-4 p-4">
            {editing ? (
                <>
                    <Field id="schema-name" label={LABELS.word.name.label}>
                        <Input
                            id="schema-name"
                            value={named}
                            onChange={(event) => {
                                onNamed(event.target.value)
                            }}
                        />
                    </Field>
                    <Field id="schema-description" label={LABELS.word.description}>
                        <Textarea
                            id="schema-description"
                            className="max-h-80 min-h-28"
                            value={description}
                            placeholder={LABELS.schemas.description_placeholder}
                            onChange={(event) => {
                                onDescription(event.target.value)
                            }}
                        />
                    </Field>
                    {problem !== null && <Refusal problem={problem} />}
                    {verbs}
                </>
            ) : (
                <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                        {description.trim() === '' ? (
                            <p className="text-sm text-muted-foreground">{LABELS.schemas.no_description}</p>
                        ) : (
                            <Description text={description} />
                        )}
                    </div>
                    {mayWrite && toggle}
                </div>
            )}
            <CheckedBy codes={usedBy} />
        </div>
    )
}

/** The pipelines that check against this shape, each a link; nothing at all where none does. */
function CheckedBy({ codes }: { codes: readonly string[] }) {
    if (codes.length === 0) return null
    return (
        <Section title={LABELS.schemas.checked_by}>
            <ul
                className="space-y-1"
                title={`${LABELS.schemas.body_warning} ${LABELS.schemas.body_in_flight}`}
            >
                {codes.map((code) => (
                    <li key={code}>
                        <Link to={`/pipelines/${encodeURIComponent(code)}`} className="hover:underline">
                            <InlineCode value={code} tone="neutral" bare size="xs" />
                        </Link>
                    </li>
                ))}
            </ul>
        </Section>
    )
}

/** The verdict as a chip, once there is one. */
function Verdict({ shown }: { shown: CheckShown }) {
    if (shown.kind !== 'checked') return null
    return shown.check.valid ? (
        <Chip tone="good">{LABELS.schemas.tester.valid}</Chip>
    ) : (
        <Chip tone="critical">{LABELS.schemas.tester.invalid}</Chip>
    )
}

/** What the check found: the verdict in the bar, and each failure as a row that shows its place. */
function Result({ shown, onShow }: { shown: CheckShown; onShow: (error: SchemaViolation) => void }) {
    const total = shown.kind === 'checked' ? shown.check.errors.length + shown.check.omitted : 0
    return (
        <LibrarySection
            title={LABELS.schemas.tester.result_heading}
            meta={total > 0 ? counted(total, LABELS.schemas.tester.failures)(String(total)) : undefined}
            actions={<Verdict shown={shown} />}
            flush={shown.kind === 'checked' && !shown.check.valid}
            className="flex min-h-0 flex-col"
            bodyClassName="min-h-0 flex-1 overflow-y-auto"
        >
            {shown.kind === 'unreadable' && <Callout tone="warning">{shown.sentence}</Callout>}
            {shown.kind === 'checking' && (
                <p className="text-sm text-muted-foreground">{LABELS.schemas.tester.checking}</p>
            )}
            {shown.kind === 'refused' && <Refusal problem={shown.problem} />}
            {shown.kind === 'checked' && shown.check.valid && (
                <p className="text-sm text-muted-foreground">{LABELS.schemas.tester.fits}</p>
            )}
            {shown.kind === 'checked' && !shown.check.valid && (
                <Failures errors={shown.check.errors} omitted={shown.check.omitted} onShow={onShow} />
            )}
        </LibrarySection>
    )
}

function Failures({
    errors,
    omitted,
    onShow,
}: {
    errors: readonly SchemaViolation[]
    omitted: number
    onShow: (error: SchemaViolation) => void
}) {
    return (
        <ul className="divide-y divide-border" aria-label={LABELS.schemas.tester.failures_label}>
            {errors.map((error) => (
                <li key={`${error.at} ${error.schema_at} ${error.message}`}>
                    <button
                        type="button"
                        className="flex w-full min-w-0 flex-col gap-1 px-4 py-2 text-left hover:bg-muted focus-visible:bg-muted focus-visible:outline-none"
                        title={LABELS.schemas.tester.show_failure(pointerLabel(error.at))}
                        onClick={() => {
                            onShow(error)
                        }}
                    >
                        <span className="flex min-w-0 items-center justify-between gap-3">
                            {error.at === '' ? (
                                <span className="truncate text-xs text-muted-foreground">
                                    {pointerLabel(error.at)}
                                </span>
                            ) : (
                                <InlineCode value={error.at} tone="neutral" bare size="xs" />
                            )}
                            <Chip mono>{error.keyword}</Chip>
                        </span>
                        <span className="min-w-0 text-sm break-words">{error.message}</span>
                    </button>
                </li>
            ))}
            {omitted > 0 && (
                <li className="px-4 py-2 text-sm text-muted-foreground">
                    {LABELS.schemas.tester.omitted(String(omitted))}
                </li>
            )}
        </ul>
    )
}

/** A box that was emptied is that member cleared, not a member set to "". */
function given(text: string): string | null {
    const trimmed = text.trim()
    return trimmed === '' ? null : trimmed
}
