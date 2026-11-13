import { useState } from 'react'

import { GroupLabel } from '@winterop-com/sokkel-ui/GroupLabel'
import { SelectField } from '@winterop-com/sokkel-ui/SelectField'
import { TextField } from '@winterop-com/sokkel-ui/TextField'
import { Mark } from '@/components/Mark'
import { Refusal } from '@/components/Refusal'
import { GeneratedForm } from '@/components/schema/GeneratedForm'
import { useStore } from '@/hooks/use-store'
import { type ConnectionDraftForm } from '@/hooks/use-connection-draft'
import { type SurfaceEntry } from '@/lib/connections'
import { FIELD_WORDS } from '@/lib/design-system'
import { kindGlyph } from '@/lib/glyphs'
import { LABELS } from '@/lib/labels'
import { kindMarks } from '@/lib/marks'

/**
 * The boxes one connection is minted from, wherever the form asking for them stands.
 *
 * THE KIND IS CHOSEN FROM THE CATALOG, not typed. `GET /blocks` answers every contributed
 * surface, connection kinds among them, and that list is the whole of what this instance can
 * seal a credential for -- so the kind is a select over it, and a kind nothing installed is not
 * a thing this form can ask for.
 *
 * THE CONFIG IS THE KIND'S SCHEMA, the same form the panel builds beside the listing: the kind
 * is settled first, so what a control is for is known before one is drawn. Every field the kind
 * declares secret is a secret field in it, masked, and one left empty mints a connection with no
 * credential for it rather than one with an empty password. In the row of another decision the
 * form opens on what the kind requires, the rest behind one disclosure.
 *
 * WHAT A DOCUMENT ALREADY DECIDED IS NOT ASKED AGAIN. Mounted in the row of an offer that says
 * the document names a connection this instance has not got, the code and the kind are the
 * document's own and the row draws both -- so no box repeats them, and a code box that could be
 * changed would offer a create that leaves the row it stands in exactly as it was. A title and a
 * description are the credential's own screen's, for the same reason a step form opens on what
 * the document needs: what the apply is waiting for is a connection under that code.
 */
export function ConnectionFields({
    form,
    kinds,
    decided,
    ids,
}: {
    form: ConnectionDraftForm
    /** What this instance has installed, from the catalog whatever opened the form read. */
    kinds: readonly SurfaceEntry[]
    /**
     * The identity the document settled and the surface already draws, or nothing where this
     * form is the whole of the asking. A null `kind` is a carried connection declaring none, so
     * the kind is still chosen here.
     */
    decided?: { code: string; kind: string | null }
    /** What this form's control ids begin with, so two forms open at once do not share one. */
    ids: string
}) {
    const { draft, chosen } = form
    const asksKind = decided === undefined || decided.kind === null
    // Whether the code box has been left once, so it says it is empty only after somebody was there.
    const [left, setLeft] = useState(false)
    const codeIssue = left && draft.code.trim() === '' ? LABELS.connections.needs_code : null

    return (
        <>
            {decided === undefined ? (
                <div className="grid grid-cols-2 gap-3">
                    <TextField
                        id={`${ids}-code`}
                        label={LABELS.word.code}
                        required
                        requiredMark="word"
                        words={FIELD_WORDS}
                        error={codeIssue}
                        mono
                        value={draft.code}
                        onChange={form.setCode}
                        onBlur={() => {
                            setLeft(true)
                        }}
                        placeholder={LABELS.connections.code_placeholder}
                    />
                    <KindBox form={form} kinds={kinds} ids={ids} />
                </div>
            ) : (
                asksKind && <KindBox form={form} kinds={kinds} ids={ids} />
            )}

            {decided === undefined && (
                <>
                    <TextField
                        id={`${ids}-name`}
                        label={LABELS.word.name.label}
                        value={draft.name}
                        onChange={form.setName}
                    />

                    <TextField
                        id={`${ids}-description`}
                        label={LABELS.word.description}
                        multiline
                        value={draft.description}
                        onChange={form.setDescription}
                        placeholder={LABELS.connections.description_placeholder}
                    />
                </>
            )}

            {chosen !== null && (
                <div className="space-y-3">
                    <GroupLabel as="h3">{LABELS.connections.settings_heading}</GroupLabel>
                    <GeneratedForm key={chosen.id} form={form.form} fold={decided !== undefined} />
                </div>
            )}

            {form.problem !== null && <Refusal problem={form.problem} />}
        </>
    )
}

/**
 * The kind this credential is of, chosen from what the instance has installed.
 *
 * Each row carries the kind's mark beside its code, and the chosen row keeps it in the closed
 * box. The kind is written as well as marked, because a mark cannot be typed and the code is what
 * a document names the kind by.
 */
function KindBox({
    form,
    kinds,
    ids,
}: {
    form: ConnectionDraftForm
    kinds: readonly SurfaceEntry[]
    ids: string
}) {
    const marks = useStore(kindMarks)
    return (
        <SelectField
            id={`${ids}-kind`}
            label={LABELS.word.kind.label}
            required
            requiredMark="word"
            words={FIELD_WORDS}
            mono
            value={form.draft.kind}
            placeholder={LABELS.connections.choose_kind}
            options={kinds.map((one) => ({
                value: one.id,
                label: one.id,
                icon: <Mark glyph={kindGlyph(one.id, marks)} />,
            }))}
            onChange={form.chooseKind}
        />
    )
}
