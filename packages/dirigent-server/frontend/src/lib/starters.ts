/**
 * Copying a starter: the two lines a copy rewrites, and nothing else.
 *
 * A STARTER IS A DOCUMENT, NOT A TEMPLATE. There is no macro language to expand, so
 * instantiating one is a verbatim copy of its text with the top-level `code:` changed and
 * `starter` taken off the top-level `tags:`. The teaching comments, the blank lines and the
 * quoting are the point of copying a document instead of generating one, so the edit is made
 * at text level rather than through a parser that would render the document afresh.
 *
 * IT IS `dirigent_cli.starters.instantiate`, TWICE. The CLI writes the copy into a project and
 * this writes it into the editor, and a reader who did both and got two different files would
 * be right to distrust whichever one they read second. The Python module and this one are the
 * same rules in the same order, and both suites assert the same cases.
 */

/** The tag a document opts into to say it may be copied, and the one a copy drops. */
export const STARTER_TAG = 'starter'

/** The top-level `code:` line: no indentation, so a step's own `code` is never touched. */
const CODE = /^code:[^\S\n]*(.*)$/mu

/** The top-level `tags:` line, and whatever it carries on the same line. */
const TAGS = /^tags:[^\S\n]*(.*)$/mu

/** One entry of a block list under `tags:`: indentation, a dash, the value. */
const TAG_ITEM = /^[^\S\n]*-[^\S\n]*(\S.*?)[^\S\n]*$/u

/** Copy a starter's text under a new code, with the `starter` tag dropped. */
export function instantiate(source: string, code: string): string {
    return retag(recode(source, code))
}

/** Rewrite the one top-level `code:` line, leaving every other line alone. */
function recode(source: string, code: string): string {
    // A function replacement, so a `$` in the code is a character rather than a back-reference.
    return source.replace(CODE, () => `code: ${code}`)
}

/**
 * Take `starter` off the top-level `tags:`, whichever shape the list is written in.
 *
 * A document whose only tag was `starter` loses the whole `tags:` entry: an empty list says
 * less than no list at all.
 */
function retag(source: string): string {
    const found = TAGS.exec(source)
    if (found === null) return source
    const start = found.index
    const end = start + found[0].length
    const rest = (found[1] ?? '').trim()
    if (rest.startsWith('[')) return rewriteFlow(source, start, end, rest)
    if (rest !== '') return source
    return rewriteBlock(source, start, end)
}

/** Rewrite `tags: [a, b, starter]`, dropping the entry when nothing is left. */
function rewriteFlow(source: string, start: number, end: number, rest: string): string {
    const inner = rest.replace(/^\[/u, '').replace(/\]$/u, '')
    const kept = inner
        .split(',')
        .map((one) => one.trim())
        .filter((tag) => tag !== '' && tag !== STARTER_TAG)
    if (kept.length === 0) return dropLine(source, start, end)
    return `${source.slice(0, start)}tags: [${kept.join(', ')}]${source.slice(end)}`
}

/** Rewrite a block list under `tags:`, dropping the whole entry when nothing is left. */
function rewriteBlock(source: string, start: number, end: number): string {
    const lines = source.slice(end).split('\n')
    const items: { at: number; tag: string }[] = []
    for (const [index, line] of lines.entries()) {
        if (index === 0 && line.trim() === '') continue
        const matched = TAG_ITEM.exec(line)
        if (matched === null) break
        items.push({ at: index, tag: matched[1] ?? '' })
    }
    if (items.length === 0) return source
    const dropped = items.filter((item) => item.tag === STARTER_TAG).map((item) => item.at)
    if (dropped.length === 0) return source
    if (dropped.length === items.length) {
        const last = items[items.length - 1]?.at ?? 0
        return dropLine(source, start, end + lines.slice(0, last + 1).join('\n').length)
    }
    const kept = lines.filter((_line, index) => !dropped.includes(index))
    return source.slice(0, end) + kept.join('\n')
}

/** Remove a whole entry, including the newline that ended it. */
function dropLine(source: string, start: number, end: number): string {
    const tail = source.slice(end)
    return source.slice(0, start) + (tail.startsWith('\n') ? tail.slice(1) : tail)
}
