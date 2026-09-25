/**
 * The marks the installed packs declare, read once and held for every screen that draws one.
 *
 * ONE READ FOR THE WHOLE SESSION. What a pack declares is fixed while a process is up, so this
 * is asked for once, when there is a session, and never again -- and a screen reads the store
 * rather than the catalog, so a listing that needs no schemas asks for none.
 *
 * WHICH MARK IS DRAWN IS `lib/glyphs`'s, NOT THIS FILE'S. All that is held here is the path data
 * the catalog answered with; `kindGlyph` decides what a kind wears, and holds a declared mark to
 * what registration held it to before it is drawn.
 */

import { apiJson } from '@/lib/api'
import { NO_MARKS, type KindMarks } from '@/lib/glyphs'
import { createStore } from '@/lib/store'

/** The host's merged view of every contribution. `Catalog`, of which one member is read here. */
interface Catalog {
    connection_kinds: { id: string; mark: string | null }[]
}

export const kindMarks = createStore<KindMarks>(NO_MARKS)

let asked = false

/**
 * Read the catalog once and hold every mark a connection kind declares.
 *
 * A read that fails changes nothing: every kind keeps the mark this bundle knows it by, or the
 * neutral one, which is what a screen draws before the read lands anyway.
 */
export function loadKindMarks(): void {
    if (asked) return
    asked = true
    void apiJson<Catalog>('/blocks').then(
        (catalog) => {
            const declared = new Map<string, string>()
            for (const entry of catalog.connection_kinds) {
                if (entry.mark !== null && entry.mark !== '') declared.set(entry.id, entry.mark)
            }
            if (declared.size > 0) kindMarks.set(declared)
        },
        () => {
            // Nothing to hold and nothing to say: the neutral mark is already what is drawn.
            // The flag goes back, so a later ask is a second attempt rather than a refusal.
            asked = false
        },
    )
}
