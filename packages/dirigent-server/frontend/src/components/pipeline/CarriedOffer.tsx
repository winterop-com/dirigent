import { useState, type ReactNode } from 'react'

import { ConnectionFields } from '@/components/connections/ConnectionFields'
import { KindChip } from '@/components/KindChip'
import { Refusable } from '@/components/Refusable'
import { Button } from '@/components/ui/button'
import { useConnectionDraft } from '@/hooks/use-connection-draft'
import { actionWord, connectionNote, offerBlocked, type CarriedItem } from '@/lib/carried'
import { type ConnectionOut, type SurfaceEntry } from '@/lib/connections'
import { LABELS } from '@/lib/labels'
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
 * is a collision nothing here resolves, and `missing` is what the apply itself refuses. The last
 * two are why the button is shut, and the line under the list says which.
 *
 * A MISSING CONNECTION IS ANSWERED IN ITS OWN ROW. Nothing here stores a credential out of a
 * document, so the way forward is the form that does -- and that form opens under the row that
 * said so, rather than at the end of a link. A document being written has no version behind it,
 * so leaving this screen to go and mint a credential threw away everything somebody had typed:
 * a control that destroyed the work it was offered to rescue. The row expands instead, the kind
 * and the code the document already declares are not asked for again, and the row turns
 * `already here` the moment the credential exists.
 */
export function CarriedOffer({
    items,
    reading,
    kinds,
    onCreated,
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
}) {
    const blocked = offerBlocked(items)
    const note = connectionNote(items)
    // Which row's form stands open, by the code it is about. One at a time: two forms would be
    // two credentials half typed with one Apply behind them.
    const [opened, setOpened] = useState<string | null>(null)

    return (
        <section className="space-y-2">
            <h2 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                {LABELS.editor.carried.title}
            </h2>
            {reading ? (
                <p className="text-xs text-muted-foreground">{LABELS.shell.reading}</p>
            ) : (
                <>
                    <ul className="space-y-1 text-xs">
                        {items.map((item) => (
                            <OfferRow
                                key={`${item.kind}:${item.code}`}
                                item={item}
                                under={
                                    opened === item.code && kinds !== null ? (
                                        <MintConnection
                                            item={item}
                                            kinds={kinds}
                                            onCreated={(row) => {
                                                setOpened(null)
                                                onCreated(row)
                                            }}
                                            onCancel={() => {
                                                setOpened(null)
                                            }}
                                        />
                                    ) : undefined
                                }
                            >
                                {opened !== item.code && kinds !== null && offersForm(item, kinds) && (
                                    <MintControl
                                        code={item.code}
                                        onOpen={() => {
                                            setOpened(item.code)
                                        }}
                                    />
                                )}
                            </OfferRow>
                        ))}
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
        <li className="space-y-1">
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

/** The row's control, which says the verb and hears the whole of what it acts on. */
function MintControl({ code, onOpen }: { code: string; onOpen: () => void }) {
    return (
        <Button
            variant="outline"
            size="sm"
            className="shrink-0"
            aria-label={LABELS.editor.carried.create_row(code)}
            onClick={onOpen}
        >
            {LABELS.action.create.verb}
        </Button>
    )
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
 * Whether this row can open a form that would mint what it is missing.
 *
 * A CONTROL ONLY EVER CLAIMS WHAT THE SITUATION SUPPORTS. A schema is stored by the apply
 * itself and has no form here; a connection whose kind this instance has not installed has no
 * config schema to ask against and no create that could succeed, so that row says `missing` and
 * offers nothing. A carried connection declaring no kind at all is offered one, because the
 * form is where a kind is chosen.
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
