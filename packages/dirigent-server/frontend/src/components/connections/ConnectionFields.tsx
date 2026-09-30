import { SecretField } from '@/components/connections/SecretField'
import { Mark } from '@/components/Mark'
import { Refusal } from '@/components/Refusal'
import { SchemaForm } from '@/components/pipeline/SchemaForm'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useStore } from '@/hooks/use-store'
import { type ConnectionDraftForm } from '@/hooks/use-connection-draft'
import { type SurfaceEntry } from '@/lib/connections'
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
 * is settled first, so what a control is for is known before one is drawn.
 *
 * A SECRET IS NOT A SCHEMA FIELD HERE. The schema says a secret is a string, and rendering it as
 * one would put a credential in a text box. Every field the kind declares secret is taken out of
 * the generated form and drawn below it as a write-only password box, and one left empty mints a
 * connection with no credential for it rather than one with an empty password.
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

    return (
        <>
            {decided === undefined ? (
                <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-2">
                        <Label htmlFor={`${ids}-code`}>{LABELS.word.code}</Label>
                        <Input
                            id={`${ids}-code`}
                            className="font-mono"
                            value={draft.code}
                            onChange={(event) => {
                                form.setCode(event.target.value)
                            }}
                            placeholder={LABELS.connections.code_placeholder}
                        />
                    </div>
                    <KindBox form={form} kinds={kinds} ids={ids} />
                </div>
            ) : (
                asksKind && <KindBox form={form} kinds={kinds} ids={ids} />
            )}

            {decided === undefined && (
                <>
                    <div className="space-y-2">
                        <Label htmlFor={`${ids}-name`}>{LABELS.word.name.label}</Label>
                        <Input
                            id={`${ids}-name`}
                            value={draft.name}
                            onChange={(event) => {
                                form.setName(event.target.value)
                            }}
                        />
                    </div>

                    <div className="space-y-2">
                        <Label htmlFor={`${ids}-description`}>{LABELS.word.description}</Label>
                        <Textarea
                            id={`${ids}-description`}
                            className="h-24"
                            value={draft.description}
                            onChange={(event) => {
                                form.setDescription(event.target.value)
                            }}
                            placeholder={LABELS.connections.description_placeholder}
                        />
                    </div>
                </>
            )}

            {chosen !== null && (
                <div className="space-y-3">
                    <p className="text-xs font-semibold tracking-wide text-faint uppercase">
                        {LABELS.connections.settings_heading}
                    </p>
                    <div className="space-y-3">
                        <SchemaForm
                            fields={form.fields}
                            values={draft.values}
                            problems={form.problems}
                            stated={form.stated}
                            // A form standing in a row of another decision opens on what the
                            // kind requires, the rest behind the one link every generated form
                            // folds them behind: the list this row is part of has to stay on
                            // screen beside it. The dialog is the asking itself and folds
                            // nothing.
                            fold={decided !== undefined}
                            onChange={form.setSetting}
                            onTouch={form.touch}
                            onUnreadable={form.markUnreadable}
                        />
                        {chosen.secret_fields.map((name) => (
                            <SecretField
                                key={name}
                                id={`${ids}-secret-${name}`}
                                name={name}
                                stored={false}
                                value={draft.secrets[name] ?? ''}
                                onChange={(typed) => {
                                    form.setSecret(name, typed)
                                }}
                            />
                        ))}
                    </div>
                </div>
            )}

            {form.problem !== null && <Refusal problem={form.problem} />}
        </>
    )
}

/** The kind this credential is of, chosen from what the instance has installed. */
function KindBox({
    form,
    kinds,
    ids,
}: {
    form: ConnectionDraftForm
    kinds: readonly SurfaceEntry[]
    ids: string
}) {
    const chosen = form.chosen
    return (
        <div className="space-y-2">
            <Label htmlFor={`${ids}-kind`}>{LABELS.word.kind.label}</Label>
            <Select
                value={form.draft.kind}
                onValueChange={(picked) => {
                    form.chooseKind(String(picked))
                }}
            >
                <SelectTrigger id={`${ids}-kind`} className="w-full font-mono">
                    {/* The chosen row keeps its mark in the closed box, so the row somebody
                        picked is the row they are looking at. Nothing chosen draws the
                        placeholder, which names no kind and so wears no mark. */}
                    <SelectValue placeholder={LABELS.connections.choose_kind}>
                        {chosen === null ? undefined : () => <KindRow kind={chosen.id} />}
                    </SelectValue>
                </SelectTrigger>
                <SelectContent>
                    {kinds.map((one) => (
                        <SelectItem key={one.id} value={one.id} className="font-mono">
                            <KindRow kind={one.id} />
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}

/**
 * One kind as the form offers it: the mark, and the code it is chosen by.
 *
 * The kind is written as well as marked, because a mark cannot be typed and the code is what a
 * document names the kind by.
 */
function KindRow({ kind }: { kind: string }) {
    const marks = useStore(kindMarks)
    return (
        <span className="flex items-center gap-2">
            <Mark glyph={kindGlyph(kind, marks)} />
            {kind}
        </span>
    )
}
