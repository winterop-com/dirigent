import { useMemo, useState } from 'react'

import { CodePane } from '@/components/pipeline/CodePane'
import { Refusable } from '@/components/Refusable'
import { Refusal } from '@/components/Refusal'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { WindowedPane } from '@/components/WindowedPane'
import { useMayWrite } from '@/hooks/use-may-write'
import { type JsonMap, type Problem } from '@/lib/api'
import { headingOf } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { local, refusalOf } from '@/lib/refusal'
import {
    bodyText,
    deleteSchema,
    schemaPatch,
    updateSchema,
    validatedBy,
    whyKept,
    type SchemaOut,
} from '@/lib/schemas'

/** The media type that asks for the meta-schema of the draft the server validates with. */
const SCHEMA_MEDIA_TYPE = 'application/schema+json'

/**
 * One stored schema, read and corrected beside the listing.
 *
 * A SCHEMA IS EDITED WHERE IT IS READ. `PATCH /schemas/{code}` changes the name, the description
 * and the body, so those are the three boxes: a shape somebody got wrong is fixed on the screen
 * that shows it rather than deleted and written again under the same code.
 *
 * THE CODE IS FIXED. The route addresses the schema by it and `SchemaUpdate` has no member for
 * it, so it is the heading and never a box. A schema under a different code is a different
 * schema, and every `validate.schema` step and every `requires.schemas` entry naming the old one
 * would be naming nothing.
 *
 * THE BODY IS A SCHEMA DOCUMENT, NOT A JSON VALUE. It is written in the same Monaco the New
 * schema dialog writes it in, against `application/schema+json` -- so 2020-12's own keywords
 * complete as they are typed and a value the draft does not take is marked where it was written,
 * which is the half of the check the server would otherwise report a round trip later. The pane
 * and its window name one path, so monaco hands them one buffer.
 *
 * A DIFFERENT SCHEMA IS A DIFFERENT FORM. The screen keys this on the code, so choosing another
 * row builds a new form rather than carrying a half-typed shape onto the schema it was not
 * typed for.
 *
 * NOTHING IS SENT THAT DID NOT CHANGE. `schemaPatch` composes the body out of what moved, so a
 * name nobody touched is not written back, and a form with no edits at all says it is saved
 * without asking the server anything.
 *
 * THE DESCRIPTION IS DRAWN ONCE, AND IT IS THE BOX. A panel that is a form has its values in its
 * controls; rendering the same sentence as prose above the box it is typed in is one fact twice
 * on a surface with nothing between the two copies.
 *
 * AN EDIT IS OFFERED UNDER A DEPENDENCY AND A REMOVAL IS NOT. Correcting a shape every pipeline
 * should now validate against is what this panel is for, so Save stays live and the pipelines
 * that name the code are drawn beside the body -- the decision is made for them, and a count is
 * not a name. `DELETE /schemas/{code}` refuses a code a stored pipeline names, so Delete is shut
 * before it is pressed instead of answering a refusal afterwards.
 */
export function SchemaPanel({
    schema,
    onSaved,
    onDeleted,
}: {
    schema: SchemaOut
    /** Called with what the server answered, so the row behind updates without a re-read. */
    onSaved: (row: SchemaOut) => void
    onDeleted: () => void
}) {
    const opened = useMemo(() => bodyText(schema), [schema])
    const [named, setNamed] = useState(schema.name ?? '')
    const [description, setDescription] = useState(schema.description ?? '')
    const [text, setText] = useState(opened)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)
    const [saved, setSaved] = useState(false)
    const [removing, setRemoving] = useState(false)

    const heading = headingOf(schema)
    const write = useMayWrite('admin')
    // The role is asked first: an account that may not write at all is not told about a
    // dependency it could do nothing with either way.
    const kept = write.may ? whyKept(schema) : undefined
    const why = write.why ?? kept
    const validated = validatedBy(schema)

    // Typing into either pane is an edit, so what the foot said about the last save is spent.
    const edited = (next: string) => {
        setText(next)
        setSaved(false)
    }

    const send = () => {
        setProblem(null)
        let body: JsonMap | undefined
        if (text !== opened) {
            try {
                body = JSON.parse(text || '{}') as JsonMap
            } catch (error) {
                setProblem(local(LABELS.schemas.unreadable(String(error))))
                return
            }
        }
        const payload = schemaPatch(schema, given(named), given(description), body)
        if (payload === null) {
            setSaved(true)
            return
        }
        setBusy(true)
        void updateSchema(schema.code, payload)
            .then(
                (row) => {
                    setSaved(true)
                    onSaved(row)
                },
                (error: unknown) => {
                    setProblem(refusalOf(error))
                },
            )
            .finally(() => {
                setBusy(false)
            })
    }

    const remove = () => {
        setRemoving(true)
        setProblem(null)
        void deleteSchema(schema.code)
            .then(onDeleted, (error: unknown) => {
                setProblem(refusalOf(error))
            })
            .finally(() => {
                setRemoving(false)
            })
    }

    return (
        <div className="space-y-4 p-4">
            <div>
                <p className="flex items-center gap-2">
                    <span
                        className={
                            heading.named ? 'text-sm font-semibold' : 'font-mono text-sm font-semibold'
                        }
                    >
                        {heading.title}
                    </span>
                    {heading.code !== null && (
                        <span className="font-mono text-xs text-muted-foreground">{heading.code}</span>
                    )}
                </p>
            </div>

            <div className="space-y-1.5">
                <Label htmlFor="schema-name">{LABELS.word.name.label}</Label>
                <Input
                    id="schema-name"
                    value={named}
                    disabled={!write.may}
                    onChange={(event) => {
                        setNamed(event.target.value)
                        setSaved(false)
                    }}
                />
                <p className="text-xs text-faint">{LABELS.schemas.name_hint}</p>
            </div>

            <div className="space-y-1.5">
                <Label htmlFor="schema-description">{LABELS.word.description}</Label>
                <Textarea
                    id="schema-description"
                    className="h-24"
                    value={description}
                    placeholder={LABELS.schemas.description_placeholder}
                    disabled={!write.may}
                    onChange={(event) => {
                        setDescription(event.target.value)
                        setSaved(false)
                    }}
                />
            </div>

            <div className="space-y-1.5">
                <Label>{LABELS.word.schema.label}</Label>
                <p className="text-xs text-faint">{LABELS.schemas.body_warning}</p>
                {validated !== null && (
                    <>
                        <p className="text-xs text-muted-foreground">{validated}</p>
                        <p className="text-xs text-faint">{LABELS.schemas.body_in_flight}</p>
                    </>
                )}
                <WindowedPane
                    name={LABELS.schemas.body_title(schema.code)}
                    className="overflow-hidden rounded-md border border-border bg-background"
                    windowed={
                        <CodePane
                            value={text}
                            mediaType={SCHEMA_MEDIA_TYPE}
                            path={bufferOf(schema.code)}
                            label={LABELS.shell.in_window(LABELS.schemas.body_title(schema.code))}
                            readOnly={!write.may}
                            className="min-h-0 flex-1"
                            onChange={edited}
                        />
                    }
                >
                    <CodePane
                        value={text}
                        mediaType={SCHEMA_MEDIA_TYPE}
                        path={bufferOf(schema.code)}
                        label={LABELS.schemas.editor_label}
                        readOnly={!write.may}
                        className="h-64 min-h-40"
                        onChange={edited}
                    />
                </WindowedPane>
            </div>

            {problem !== null && <Refusal problem={problem} />}

            <div className="flex flex-wrap items-center gap-2">
                <Refusable why={write.why}>
                    <Button
                        size="sm"
                        disabled={busy || removing || !write.may}
                        title={write.why}
                        onClick={send}
                    >
                        {busy ? LABELS.action.save.busy : LABELS.action.save.verb}
                    </Button>
                </Refusable>
                {saved && <span className="text-xs text-muted-foreground">{LABELS.action.save.done}</span>}
                <Refusable why={why}>
                    <Button
                        variant="outline"
                        size="sm"
                        className="destructive-action ml-auto"
                        disabled={busy || removing || !write.may || kept !== undefined}
                        title={why}
                        onClick={remove}
                    >
                        {removing ? LABELS.action.delete.busy : LABELS.action.delete.verb}
                    </Button>
                </Refusable>
            </div>
        </div>
    )
}

/** The buffer this schema is held in, which the pane and its window both name. */
function bufferOf(code: string): string {
    return `schemas/${code}`
}

/** A box that was emptied is that member cleared, not a member set to "". */
function given(text: string): string | null {
    const trimmed = text.trim()
    return trimmed === '' ? null : trimmed
}
