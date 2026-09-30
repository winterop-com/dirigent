import { useState, type ReactNode } from 'react'

import { ConnectionFields } from '@/components/connections/ConnectionFields'
import { JsonBlock } from '@/components/JsonBlock'
import { KindChip } from '@/components/KindChip'
import { Refusable } from '@/components/Refusable'
import { Refusal } from '@/components/Refusal'
import { Button } from '@/components/ui/button'
import { useConnectionDraft } from '@/hooks/use-connection-draft'
import { useMayWrite } from '@/hooks/use-may-write'
import { type Problem } from '@/lib/api'
import { actionWord, connectionNote, mayUpdate, offerBlocked, type CarriedItem } from '@/lib/carried'
import { type ConnectionOut, type SurfaceEntry } from '@/lib/connections'
import { LABELS } from '@/lib/labels'
import { refusalOf } from '@/lib/refusal'
import { updateSchema, wholeSchema } from '@/lib/schemas'
import { cn } from '@/lib/utils'

/** What one carried entry is called on its own line, in the reader's word rather than the wire's. */
const NOUNS: Readonly<Record<CarriedItem['kind'], string>> = LABELS.editor.carried.noun

/**
 * The way through a refusal made for a carried section: what applying stores, and what it does not.
 *
 * THE REFUSAL IS NOT REDRAWN HERE. The server writes one sentence for the CLI, for this screen
 * and for every other client, so it states the fact and names no tool; what a person on this
 * screen does about it is this list and these controls, and printing that sentence over them
 * would put one fact on screen three times with the least actionable copy loudest.
 *
 * EVERY ROW SAYS WHICH OF THE FOUR CASES IT IS. `create` is stored from the document, `already
 * here` is the instance's own under that code and equal to what the document carries, `differs`
 * is a collision the row itself settles, and `missing` is what the apply itself refuses. The
 * last two are why the button is shut, and the line under the list says which.
 *
 * A MISSING CONNECTION IS ANSWERED IN ITS OWN ROW. Nothing here stores a credential out of a
 * document, so the way forward is the form that does -- and that form opens under the row that
 * said so, rather than at the end of a link. A document being written has no version behind it,
 * so leaving this screen to go and mint a credential threw away everything somebody had typed:
 * a control that destroyed the work it was offered to rescue. The row expands instead, the kind
 * and the code the document already declares are not asked for again, and the row turns
 * `already here` the moment the credential exists.
 *
 * A COLLIDING SCHEMA IS ANSWERED THE SAME WAY, AND IT IS THE OTHER HALF OF THE SAME FAULT. What
 * stood beside `differs` was a sentence naming two remedies, both of them the document author's:
 * change what the document carries, or carry it under a code of its own. The third -- update the
 * stored schema to what the document carries -- is the right one often enough that leaving it out
 * made the dialog a dead end, and the browser could not take it at all. So that row expands too,
 * over what the instance holds; it goes to the same place a link to Schemas would have gone, at
 * the same cost to the document, which is none.
 *
 * APPLYING STILL REPLACES NOTHING. The line over this list counts what applying stores, and a
 * replacement folded into that button would make it untrue: one press would both store what this
 * document carries and change what another author's pipeline validates against. It is pressed
 * here, on its own, and the confirm is drawn once the collision it was shut for has gone.
 */
export function CarriedOffer({
    items,
    reading,
    kinds,
    onCreated,
    onUpdated,
}: {
    items: readonly CarriedItem[]
    reading: boolean
    /**
     * The connection kinds this instance has installed, or null while the catalog is unread.
     *
     * A row offers no form until it has landed: what a form would ask for is the kind's own
     * config schema, and a create sent without one would mint a credential holding nothing.
     */
    kinds: readonly SurfaceEntry[] | null
    /** Called once a row has minted what it was missing, so the offer asks the instance again. */
    onCreated: (row: ConnectionOut) => void
    /** Called once a row has replaced a stored schema, for the same reason. */
    onUpdated: () => void
}) {
    const blocked = offerBlocked(items)
    const note = connectionNote(items)
    // Which row stands open, by the row it is about -- a schema and a connection may be coded
    // the same. One at a time: two open rows would be two half-made things with one Apply
    // behind them.
    const [opened, setOpened] = useState<string | null>(null)

    return (
        <section className="min-w-0 space-y-2">
            <h2 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                {LABELS.editor.carried.title}
            </h2>
            {reading ? (
                <p className="text-xs text-muted-foreground">{LABELS.shell.reading}</p>
            ) : (
                <>
                    <ul className="space-y-1 text-xs">
                        {items.map((item) => {
                            const row = rowKey(item)
                            const standing = opened === row
                            const shut = () => {
                                setOpened(null)
                            }
                            return (
                                <OfferRow
                                    key={row}
                                    item={item}
                                    under={
                                        standing ? (
                                            <Opened
                                                item={item}
                                                kinds={kinds}
                                                onCreated={(made) => {
                                                    shut()
                                                    onCreated(made)
                                                }}
                                                onUpdated={() => {
                                                    shut()
                                                    onUpdated()
                                                }}
                                                onCancel={shut}
                                            />
                                        ) : undefined
                                    }
                                >
                                    {!standing && (
                                        <RowControl
                                            item={item}
                                            kinds={kinds}
                                            onOpen={() => {
                                                setOpened(row)
                                            }}
                                        />
                                    )}
                                </OfferRow>
                            )
                        })}
                    </ul>
                    {blocked !== undefined && (
                        <p className="text-xs break-words text-critical" role="alert">
                            {blocked}
                        </p>
                    )}
                    {note !== undefined && <p className="text-xs text-muted-foreground">{note}</p>}
                </>
            )}
        </section>
    )
}

/**
 * One carried entry's line, and whatever a row opens under itself.
 *
 * THE LINE IS THE SAME FOUR THINGS ON EVERY ROW -- what kind of thing it is, the code, the kind
 * a connection declares, and what becomes of it -- so a reader compares down the column rather
 * than down four shapes. What a row can do about its own case goes after that, and what it opens
 * goes under it: a form raised over this dialog would put a scrim over the list it is about.
 */
function OfferRow({
    item,
    children,
    under,
}: {
    item: CarriedItem
    /** The row's own control, drawn while nothing it opened stands. */
    children?: ReactNode
    /** What the row opened, in the row's own place. */
    under?: ReactNode
}) {
    return (
        <li className="min-w-0 space-y-1">
            <div className="flex items-baseline gap-2">
                <span className="text-faint">{NOUNS[item.kind]}</span>
                <span className="font-mono break-all">{item.code}</span>
                {item.connectionKind !== null && <KindChip kind={item.connectionKind} />}
                <span className={cn('ml-auto shrink-0', inkOf(item))}>{actionWord(item)}</span>
                {children}
            </div>
            {under !== undefined && <div className="pb-1">{under}</div>}
        </li>
    )
}

/** Which row this is, which is what tells two rows coded the same apart. */
function rowKey(item: CarriedItem): string {
    return `${item.kind}:${item.code}`
}

/**
 * The row's own control, where its case has one that would do something.
 *
 * A CONTROL ONLY EVER CLAIMS WHAT THE SITUATION SUPPORTS, so the row that has neither case
 * draws nothing at all: a connection the instance already holds, a schema the apply itself
 * stores, a code this bundle has nothing to offer for.
 */
function RowControl({
    item,
    kinds,
    onOpen,
}: {
    item: CarriedItem
    kinds: readonly SurfaceEntry[] | null
    onOpen: () => void
}) {
    if (kinds !== null && offersForm(item, kinds)) {
        return (
            <RowButton said={LABELS.editor.carried.create_row(item.code)} onOpen={onOpen}>
                {LABELS.action.create.verb}
            </RowButton>
        )
    }
    if (mayUpdate(item)) {
        return (
            <RowButton said={LABELS.editor.carried.update_row(item.code)} onOpen={onOpen}>
                {LABELS.action.update.verb}
            </RowButton>
        )
    }
    return null
}

/** The control itself: the verb on it, and the whole of what it acts on on its name. */
function RowButton({ said, onOpen, children }: { said: string; onOpen: () => void; children: ReactNode }) {
    return (
        <Button variant="outline" size="sm" className="shrink-0" aria-label={said} onClick={onOpen}>
            {children}
        </Button>
    )
}

/** What the open row holds, which is the form or the decision its own case needs. */
function Opened({
    item,
    kinds,
    onCreated,
    onUpdated,
    onCancel,
}: {
    item: CarriedItem
    kinds: readonly SurfaceEntry[] | null
    onCreated: (row: ConnectionOut) => void
    onUpdated: () => void
    onCancel: () => void
}) {
    if (item.kind === 'connection') {
        if (kinds === null) return null
        return <MintConnection item={item} kinds={kinds} onCreated={onCreated} onCancel={onCancel} />
    }
    return <UpdateSchema item={item} onUpdated={onUpdated} onCancel={onCancel} />
}

/**
 * Mint the connection one row says this instance has not got, in that row's own place.
 *
 * THE CODE AND THE KIND ARE THE DOCUMENT'S. They are what the row above draws, and a create
 * under any other code would leave the apply refused for the same reason -- so neither is a box
 * here, and `ConnectionFields` is handed both as decided.
 *
 * A CREDENTIAL STILL COMES FROM A PERSON. Nothing reads the connection the document carries:
 * its config can hold a secret in a field the kind declares secret and in one it does not,
 * since a `sql` or a `git` url carries a password inline, so what this form starts on is empty
 * and every value in it is typed here.
 */
function MintConnection({
    item,
    kinds,
    onCreated,
    onCancel,
}: {
    item: CarriedItem
    kinds: readonly SurfaceEntry[]
    onCreated: (row: ConnectionOut) => void
    onCancel: () => void
}) {
    const form = useConnectionDraft(kinds, item.code, item.connectionKind)

    return (
        <div className="space-y-3 rounded-lg border border-border bg-secondary/30 p-2">
            <ConnectionFields
                form={form}
                kinds={kinds}
                decided={{ code: item.code, kind: item.connectionKind }}
                ids={`carried-${item.code}`}
            />
            {/* A WAY BACK AND A WAY FORWARD. Cancel gives the row its control back and writes
                nothing; Create is drawn and shut until the form would go through. */}
            <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={onCancel}>
                    {LABELS.action.cancel}
                </Button>
                <Refusable why={form.shut}>
                    <Button
                        size="sm"
                        disabled={form.busy || form.shut !== undefined}
                        title={form.shut}
                        onClick={() => {
                            form.create(onCreated)
                        }}
                    >
                        {form.busy ? LABELS.action.create.busy : LABELS.action.create.verb}
                    </Button>
                </Refusable>
            </div>
        </div>
    )
}

/**
 * Replace the schema one row says the instance holds a different shape under, in that row's place.
 *
 * WHAT IS SHOWN IS WHAT WOULD BE LOST. The shape the document carries is in the editor behind
 * this dialog; the one the instance holds is the half the reader cannot otherwise see without
 * leaving a document nothing has applied, so it is drawn here -- whole, in the pane a schema is
 * read in everywhere else, with the window that pane always offers. Nothing caps it: the surface
 * scrolls and a block inside it does not.
 *
 * THE IDENTITY TRAVELS WITH THE BODY. Storing a schema reads its own `title` and `description`
 * where the write names neither, and `PATCH /schemas/{code}` reads nothing, so `wholeSchema`
 * sends all three -- or the instance keeps the labels of a shape it no longer holds.
 *
 * THE ROW IS THE REPORT. What the write did is the row turning `already here` and the confirm
 * appearing behind it, which is where the reader is already looking; a line saying so as well
 * would be the same fact twice.
 */
function UpdateSchema({
    item,
    onUpdated,
    onCancel,
}: {
    item: CarriedItem
    onUpdated: () => void
    onCancel: () => void
}) {
    const [busy, setBusy] = useState(false)
    const [problem, setProblem] = useState<Problem | null>(null)
    const write = useMayWrite('admin')
    const words = LABELS.editor.carried

    const update = () => {
        setBusy(true)
        setProblem(null)
        void updateSchema(item.code, wholeSchema(item.body ?? {}))
            .then(onUpdated, (error: unknown) => {
                setProblem(refusalOf(error))
            })
            .finally(() => {
                setBusy(false)
            })
    }

    return (
        <div className="min-w-0 space-y-3 rounded-lg border border-border bg-secondary/30 p-2">
            <p className="text-xs font-semibold tracking-wide text-faint uppercase">{words.held_heading}</p>
            <JsonBlock title={words.held_body(item.code)} text={JSON.stringify(item.stored, null, 2)} />
            <p className="text-xs text-muted-foreground">{words.update_note}</p>
            {problem !== null && <Refusal problem={problem} />}
            {/* A WAY BACK AND A WAY FORWARD. Cancel gives the row its control back and writes
                nothing; Update is shut only for an account that may not store a schema. */}
            <div className="flex justify-end gap-2">
                <Button variant="ghost" size="sm" onClick={onCancel}>
                    {LABELS.action.cancel}
                </Button>
                <Refusable why={write.why}>
                    <Button size="sm" disabled={busy || !write.may} title={write.why} onClick={update}>
                        {busy ? LABELS.action.update.busy : words.update_confirm}
                    </Button>
                </Refusable>
            </div>
        </div>
    )
}

/**
 * Whether this row can open a form that would mint what it is missing.
 *
 * A CONTROL ONLY EVER CLAIMS WHAT THE SITUATION SUPPORTS. A schema the instance has nothing
 * under is stored by the apply itself and has no form here; a connection whose kind this
 * instance has not installed has no config schema to ask against and no create that could
 * succeed, so that row says `missing` and offers nothing. A carried connection declaring no kind
 * at all is offered one, because the form is where a kind is chosen.
 */
function offersForm(item: CarriedItem, kinds: readonly SurfaceEntry[]): boolean {
    if (item.kind !== 'connection' || item.action !== 'missing') return false
    if (item.connectionKind === null) return kinds.length > 0
    return kinds.some((one) => one.id === item.connectionKind)
}

/** The ink a row's word is read in, which is the one a requirements list already reads in. */
function inkOf(item: CarriedItem): string {
    switch (item.action) {
        case 'create':
            return 'text-foreground'
        case 'held':
            return 'text-good'
        case 'differs':
        case 'missing':
            return 'text-critical'
    }
}
