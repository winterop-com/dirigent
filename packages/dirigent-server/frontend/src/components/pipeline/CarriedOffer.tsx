import { Link } from 'react-router'

import { KindChip } from '@/components/KindChip'
import { Button } from '@/components/ui/button'
import { actionWord, connectionNote, missingConnections, offerBlocked, type CarriedItem } from '@/lib/carried'
import { newConnectionPath } from '@/lib/connections'
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
 * A MISSING CONNECTION IS A DOOR, NOT AN INSTRUCTION. Nothing here stores a credential out of a
 * document, so the way forward is the form that does -- reached with the kind and the code it
 * needs already in the address, because both are the document's own and neither is a secret.
 */
export function CarriedOffer({ items, reading }: { items: readonly CarriedItem[]; reading: boolean }) {
    const blocked = offerBlocked(items)
    const note = connectionNote(items)
    const doors = missingConnections(items)

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
                            <li key={`${item.kind}:${item.code}`} className="flex items-baseline gap-2">
                                <span className="text-faint">{NOUNS[item.kind]}</span>
                                <span className="font-mono break-all">{item.code}</span>
                                {item.connectionKind !== null && <KindChip kind={item.connectionKind} />}
                                <span className={cn('ml-auto shrink-0', inkOf(item))}>
                                    {actionWord(item)}
                                </span>
                            </li>
                        ))}
                    </ul>
                    {blocked !== undefined && (
                        <p className="text-xs break-words text-critical" role="alert">
                            {blocked}
                        </p>
                    )}
                    {note !== undefined && <p className="text-xs text-muted-foreground">{note}</p>}
                    {doors.length > 0 && (
                        <p className="flex flex-wrap gap-2 pt-1">
                            {doors.map((item) => (
                                <Button
                                    key={item.code}
                                    variant="outline"
                                    size="sm"
                                    render={
                                        <Link to={newConnectionPath(item.connectionKind ?? '', item.code)} />
                                    }
                                >
                                    {doors.length === 1
                                        ? LABELS.connections.new
                                        : `${LABELS.connections.new} ${item.code}`}
                                </Button>
                            ))}
                        </p>
                    )}
                </>
            )}
        </section>
    )
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
