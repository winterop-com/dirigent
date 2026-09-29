/**
 * How a refusal's code becomes a sentence, and where the sentence for a pack's code comes from.
 *
 * TWO TABLES, ONE LOOKUP. `LABELS.refused` is this bundle's own, translated with every other word
 * it says. What it cannot hold is a pack's codes, because which packs are installed is the
 * instance's business, so those are read once from `GET /labels` and consulted after it.
 *
 * ONE READ FOR THE WHOLE SESSION, as `lib/marks` reads the marks: what a pack contributes is
 * fixed while the instance is up. A read that fails changes nothing -- every refusal falls back
 * to the `detail` the server rendered, which is what is drawn before the read lands anyway.
 *
 * A HOLE WITH NO VALUE MEANS THE TEMPLATE DOES NOT FIT. A refusal carries the params its own
 * template names; if this table's sentence names one the refusal does not carry, rendering it
 * would put `{run_id}` on screen. That is a drift bug, and the honest answer to it is the
 * server's own sentence, so the render refuses and the caller falls back.
 */

import { apiJson, type JsonMap } from '@/lib/api'
import { LABELS } from '@/lib/labels'
import { createStore } from '@/lib/store'

/** A named hole in a template, as both this table and the server's own write one. */
const HOLE = /\{([a-z_][a-z0-9_]*)\}/g

/** The label table an instance serves for the codes its packs refuse under. `Labels`. */
interface Labels {
    templates: Record<string, string>
}

export const contributedWording = createStore<Record<string, string>>({})

let asked = false

/** Read the wording every installed pack refuses in, once per session. */
export function loadContributedWording(): void {
    if (asked) return
    asked = true
    void apiJson<Labels>('/labels').then(
        (served) => {
            contributedWording.set(served.templates)
        },
        () => {
            // The flag goes back, so a later ask is a second attempt rather than a refusal.
            asked = false
        },
    )
}

/** What this bundle says under one dotted code, or null where it says nothing. */
function ownTemplate(code: string): string | null {
    let held: unknown = LABELS.refused
    for (const segment of code.split('.')) {
        if (typeof held !== 'object' || held === null) return null
        held = (held as Record<string, unknown>)[segment]
    }
    return typeof held === 'string' ? held : null
}

/**
 * Write a refusal's params into a template, or refuse where it names one they do not carry.
 *
 * Exported for the test that holds this table's holes to the server's params.
 */
export function fill(template: string, params: JsonMap): string | null {
    let fits = true
    const said = template.replace(HOLE, (_whole, name: string) => {
        const value = params[name]
        if (value === undefined || value === null) {
            fits = false
            return ''
        }
        return String(value)
    })
    return fits ? said : null
}

/**
 * The sentence for one refusal code, or null where neither table holds one that fits.
 *
 * Null is what sends the caller to the server's `detail`: a code this bundle predates, a pack
 * whose wording has not been read yet, or a sentence whose holes the refusal does not fill.
 */
export function sentenceFor(code: string, params: JsonMap): string | null {
    if (code === '') return null
    const template = ownTemplate(code) ?? contributedWording.get()[code]
    return template === undefined ? null : fill(template, params)
}
