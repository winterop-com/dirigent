import { useState } from 'react'

import { DialogShell } from '@winterop-com/sokkel-ui/DialogShell'
import { TextField } from '@winterop-com/sokkel-ui/TextField'
import { Refusal } from '@/components/Refusal'
import { type JsonMap, type Problem } from '@/lib/api'
import { DIALOG_WORDS, FIELD_WORDS } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { refusalOf } from '@/lib/refusal'
import { createSchema, type SchemaOut } from '@/lib/schemas'

/** What a schema's code may be: lower case, digits and hyphens, starting with a letter or digit. */
const CODE = /^[a-z0-9][a-z0-9-]{0,199}$/

/**
 * A new schema by its code, its name and its description; the body is written on its own page.
 *
 * WHAT IS ASKED HERE IS WHAT IDENTIFIES IT. The code is what every `validate.schema` step and
 * every `requires.schemas` entry will name, so it is the one required box. The body starts as an
 * object schema naming that code as its `$id`, and the page the dialog lands on is where its shape
 * is written.
 */
export function NewSchema({
    open,
    onOpenChange,
    onCreated,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    onCreated: (row: SchemaOut) => void
}) {
    const [code, setCode] = useState('')
    const [named, setNamed] = useState('')
    const [description, setDescription] = useState('')
    const [touched, setTouched] = useState(false)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [creating, setCreating] = useState(false)

    const wanted = code.trim()
    const why =
        wanted === ''
            ? LABELS.schemas.create.code_needed
            : CODE.test(wanted)
              ? undefined
              : LABELS.schemas.create.code_shape

    const reset = () => {
        setCode('')
        setNamed('')
        setDescription('')
        setTouched(false)
        setProblem(null)
    }

    const create = () => {
        setProblem(null)
        const body: JsonMap = {
            $schema: 'https://json-schema.org/draft/2020-12/schema',
            $id: wanted,
            type: 'object',
            properties: {},
        }
        setCreating(true)
        void createSchema(body, wanted, named.trim() || null, description.trim() || null)
            .then((row) => {
                reset()
                onOpenChange(false)
                onCreated(row)
            })
            .catch((error: unknown) => {
                setProblem(refusalOf(error))
            })
            .finally(() => {
                setCreating(false)
            })
    }

    return (
        <DialogShell
            words={DIALOG_WORDS}
            open={open}
            onOpenChange={(next) => {
                if (!next) reset()
                onOpenChange(next)
            }}
            title={LABELS.schemas.new}
            confirm={{
                label: LABELS.action.create.verb,
                busyLabel: LABELS.action.create.busy,
                busy: creating,
                why,
                onConfirm: create,
            }}
        >
            <TextField
                id="new-schema-code"
                label={LABELS.word.code}
                mono
                required
                requiredMark="word"
                words={FIELD_WORDS}
                hint={LABELS.schemas.create.code_hint}
                error={touched ? (why ?? null) : null}
                value={code}
                autoFocus
                onChange={setCode}
                onBlur={() => {
                    setTouched(true)
                }}
            />
            <TextField
                id="new-schema-name"
                label={LABELS.word.name.label}
                value={named}
                onChange={setNamed}
            />
            <TextField
                id="new-schema-description"
                label={LABELS.word.description}
                multiline
                rows={3}
                maxRows={12}
                value={description}
                placeholder={LABELS.schemas.description_placeholder}
                onChange={setDescription}
            />
            {problem !== null && <Refusal problem={problem} />}
        </DialogShell>
    )
}
