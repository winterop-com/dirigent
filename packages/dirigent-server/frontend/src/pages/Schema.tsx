import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { Chip } from '@/components/ds/Chip'
import { Code } from '@/components/ds/Code'
import { IconButton } from '@/components/ds/IconButton'
import { Notice } from '@/components/ds/Notice'
import { PageHeader } from '@/components/ds/PageHeader'
import { Panel } from '@/components/ds/Panel'
import { PageState } from '@/components/PageState'
import { CodePane } from '@/components/pipeline/CodePane'
import { Refusal } from '@/components/Refusal'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useMayWrite } from '@/hooks/use-may-write'
import { useRead } from '@/hooks/use-read'
import { useSchemaSave } from '@/hooks/use-schema-save'
import { ICONS } from '@/lib/icons'
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
    whyKept,
    type SchemaOut,
} from '@/lib/schemas'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'

/** The media type that asks for the meta-schema of the draft the server validates with. */
const SCHEMA_MEDIA_TYPE = 'application/schema+json'

/** How long typing has to pause before the two texts are checked. */
const SETTLE_MS = 350

/**
 * One stored schema: its name and description, the schema beside a value, and what checking the
 * one against the other found.
 *
 * THE CHECK IS A RUN'S. `POST /schemas/$check` evaluates the value the way a `validate.schema`
 * step does, against the text in the schema editor rather than what is stored, so a shape is
 * tried before it is saved.
 *
 * TEXT THAT IS NOT JSON IS SAID WHERE IT WAS TYPED, and nothing is asked of the server for it.
 *
 * EVERY FAILURE IS MARKED WHERE IT IS. Each is a mark on the value editor at the place its pointer
 * names, and pressing one in the list selects that place.
 *
 * THE FULL-SCREEN WINDOW NAMES THE SAME TWO BUFFERS. Monaco holds one model per path, so what is
 * typed in the window is what the page shows when it closes, and the reverse. A mark belongs to
 * the model, so only the page's value editor sets them: the window draws them over the same model,
 * and closing it clears nothing.
 *
 * THE CODE IS FIXED. The route addresses the schema by it and `SchemaUpdate` has no member for
 * it, so it is the heading and never a box.
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
    const [wide, setWide] = useState(false)
    const [removing, setRemoving] = useState(false)
    const { save, busy, problem, setProblem } = useSchemaSave(schema, onSaved)
    const write = useMayWrite('admin')
    const heading = headingOf(schema)

    const input = useMemo(() => checkInput(text, value), [text, value])
    const shown = shownCheck(input, answer, text, value)

    useEffect(() => {
        if (input.kind !== 'ready') return
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
    }, [input, text, value])

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
    const valuePane = (className: string, owned: boolean) => (
        <CodePane
            value={value}
            mediaType="application/json"
            path={`schemas/${schema.code}/value`}
            label={LABELS.schemas.tester.value_label}
            wrap
            className={className}
            marks={owned ? marks : undefined}
            reveal={owned !== wide ? reveal : null}
            onChange={setValue}
        />
    )

    return (
        <>
            <PageHeader
                title={heading.title}
                code={heading.code}
                trail={[{ label: LABELS.screen.schemas.name, to: '/schemas' }]}
                aside={
                    <IconButton
                        icon={ICONS.open_in_window}
                        label={LABELS.schemas.full_screen}
                        variant="outline"
                        onClick={() => {
                            setWide(true)
                        }}
                    />
                }
                actions={[
                    {
                        id: 'example',
                        label: LABELS.schemas.tester.example,
                        variant: 'outline',
                        disabled: sample === undefined,
                        why: sample === undefined ? LABELS.schemas.tester.no_example : undefined,
                        onClick: () => {
                            setValue(JSON.stringify(sample, null, 2))
                        },
                    },
                    {
                        id: 'delete',
                        label: removing ? LABELS.action.delete.busy : LABELS.action.delete.verb,
                        variant: 'outline',
                        destructive: true,
                        disabled: busy || removing || deleteWhy !== undefined,
                        why: deleteWhy,
                        onClick: remove,
                    },
                    {
                        id: 'save',
                        label: busy ? LABELS.action.save.busy : LABELS.action.save.verb,
                        variant: 'default',
                        disabled: busy || saveWhy !== undefined,
                        why: saveWhy,
                        onClick: send,
                    },
                ]}
            />
            <div className="space-y-3">
                {problem !== null && <Refusal problem={problem} />}
                <div className="grid min-w-0 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
                    <div className="space-y-1.5">
                        <Label htmlFor="schema-name">{LABELS.word.name.label}</Label>
                        <Input
                            id="schema-name"
                            value={named}
                            disabled={!write.may}
                            title={LABELS.schemas.name_hint}
                            onChange={(event) => {
                                setNamed(event.target.value)
                            }}
                        />
                    </div>
                    <div className="space-y-1.5">
                        <Label htmlFor="schema-description">{LABELS.word.description}</Label>
                        <Textarea
                            id="schema-description"
                            className="min-h-9"
                            rows={1}
                            value={description}
                            placeholder={LABELS.schemas.description_placeholder}
                            disabled={!write.may}
                            onChange={(event) => {
                                setDescription(event.target.value)
                            }}
                        />
                    </div>
                </div>
                <CheckedBy codes={schema.used_by} />
                <div className="grid min-w-0 gap-3 lg:grid-cols-2">
                    <Panel title={LABELS.word.schema.label} inset={false}>
                        {schemaPane('h-72 min-h-72 lg:h-96')}
                    </Panel>
                    <Panel title={LABELS.schemas.tester.value_heading} inset={false}>
                        {valuePane('h-72 min-h-72 lg:h-96', true)}
                    </Panel>
                </div>
                <Result shown={shown} onShow={show} />
            </div>
            <Dialog open={wide} onOpenChange={setWide}>
                <DialogContent
                    finalFocus={false}
                    className="flex h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-none flex-col gap-3 sm:max-w-none"
                >
                    <div className="flex items-center gap-3 pr-8">
                        <DialogTitle className="font-mono text-sm">
                            {LABELS.schemas.full_screen_title(schema.code)}
                        </DialogTitle>
                        <Verdict shown={shown} />
                        <Button
                            size="sm"
                            className="ml-auto"
                            disabled={busy || saveWhy !== undefined}
                            title={saveWhy}
                            onClick={send}
                        >
                            {busy ? LABELS.action.save.busy : LABELS.action.save.verb}
                        </Button>
                    </div>
                    <div className="grid min-h-0 flex-1 gap-3 md:grid-cols-2">
                        <div className="dg-frame flex min-h-0 flex-col">{schemaPane('min-h-0 flex-1')}</div>
                        <div className="dg-frame flex min-h-0 flex-col">
                            {valuePane('min-h-0 flex-1', false)}
                        </div>
                    </div>
                    {shown.kind === 'checked' && !shown.check.valid && (
                        <div className="max-h-40 shrink-0 overflow-y-auto border-t border-border">
                            <Failures
                                errors={shown.check.errors}
                                omitted={shown.check.omitted}
                                onShow={show}
                            />
                        </div>
                    )}
                    {shown.kind === 'unreadable' && <Notice tone="warning">{shown.sentence}</Notice>}
                    {shown.kind === 'refused' && <Refusal problem={shown.problem} />}
                </DialogContent>
            </Dialog>
        </>
    )
}

/** The pipelines that check against this shape, each a link; nothing at all where none does. */
function CheckedBy({ codes }: { codes: readonly string[] }) {
    if (codes.length === 0) return null
    return (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
            <span>{LABELS.schemas.checked_by}</span>
            {codes.map((code) => (
                <Link key={code} to={`/pipelines/${encodeURIComponent(code)}`} className="hover:underline">
                    <Code value={code} tone="body" />
                </Link>
            ))}
            <span>
                {LABELS.schemas.body_warning} {LABELS.schemas.body_in_flight}
            </span>
        </p>
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
        <Panel
            title={LABELS.schemas.tester.result_heading}
            meta={total > 0 ? counted(total, LABELS.schemas.tester.failures)(String(total)) : undefined}
            aside={<Verdict shown={shown} />}
            inset={shown.kind !== 'checked' || shown.check.valid}
        >
            {shown.kind === 'unreadable' && <Notice tone="warning">{shown.sentence}</Notice>}
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
        </Panel>
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
                        className="grid w-full min-w-0 grid-cols-[minmax(0,14rem)_auto_minmax(0,1fr)] items-baseline gap-3 px-4 py-2 text-left hover:bg-muted focus-visible:bg-muted focus-visible:outline-none max-md:grid-cols-[minmax(0,1fr)_auto] max-md:py-3"
                        title={LABELS.schemas.tester.show_failure(pointerLabel(error.at))}
                        onClick={() => {
                            onShow(error)
                        }}
                    >
                        {error.at === '' ? (
                            <span className="truncate text-xs text-muted-foreground">
                                {pointerLabel(error.at)}
                            </span>
                        ) : (
                            <Code value={error.at} tone="body" />
                        )}
                        <Chip tone="mono">{error.keyword}</Chip>
                        <span className="min-w-0 text-sm break-words max-md:col-span-2">{error.message}</span>
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
