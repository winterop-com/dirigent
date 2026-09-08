/**
 * How an addressable thing is headed on screen.
 *
 * EVERY ADDRESSABLE CONCEPT CARRIES FOUR THINGS: an `id` no reader ever types, a `code` that is
 * the key it is addressed by in URLs, documents and references, an optional `name` that is a
 * display string with no identity semantics at all, and a `description`. Nothing anywhere may
 * reference a thing by its name.
 *
 * ONE DECISION, MADE ONCE. A title is the name when there is one and the code when there is
 * not, and every listing, panel header, breadcrumb, graph node and palette row asks here rather
 * than spelling `name ?? code` out again -- because a screen that spelled it out itself is a
 * screen that can disagree with the others about a name of whitespace.
 *
 * THE CODE IS ALWAYS ON SCREEN. When the title is a name, the code goes under it in mono; when
 * there is no name, the title is the code and wears the mono face itself. Either way the key
 * somebody would type into a URL or a document is in front of them, and it is never drawn twice.
 */

/** Anything addressed by a code, which may also carry a display name. */
export interface Addressable {
    code: string
    name?: string | null
}

/** How one thing is headed: what it is called, and its code when the title is not already it. */
export interface Heading {
    /** The display string: the name when there is one, else the code. */
    title: string
    /** The code to draw in mono under the title, or null when the title is the code. */
    code: string | null
    /** Whether the title is a name rather than the code, which decides the face the title wears. */
    named: boolean
}

/** What a thing is called: its name when it has one, else the code it is addressed by. */
export function titleOf(thing: Addressable): string {
    const name = thing.name
    if (name === null || name === undefined || name.trim() === '') return thing.code
    return name.trim()
}

/** The title and the code beneath it, for anywhere that draws both. */
export function headingOf(thing: Addressable): Heading {
    const title = titleOf(thing)
    const named = title !== thing.code
    return { title, code: named ? thing.code : null, named }
}

/**
 * A description as the one line a listing row has space for.
 *
 * The words as they were written, with every run of whitespace closed up -- a row truncates
 * this rather than rendering the markdown, because markdown cut off mid-heading reads as
 * neither, and drawing it would spend the renderer's chunk on a screen that has no room for it.
 */
export function oneLine(description: string): string {
    const paragraph = description.split(/\n\s*\n/, 1)[0] ?? ''
    const flat = paragraph
        .replaceAll(/\[([^\]]*)\]\([^)]*\)/g, '$1')
        .replaceAll(/^[-*+]\s+/gm, '')
        .replaceAll(/^\d+\.\s+/gm, '')
        .replaceAll(/[*_`#>]/g, '')
        .replaceAll(/\s+/g, ' ')
        .trim()
    const sentence = /^.*?[.!?](?=\s|$)/.exec(flat)
    return sentence === null ? flat : sentence[0]
}
