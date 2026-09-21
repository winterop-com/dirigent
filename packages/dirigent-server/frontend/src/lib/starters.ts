/**
 * Copying a starter: the lines a copy rewrites, and nothing else.
 *
 * A STARTER IS A DOCUMENT, NOT A TEMPLATE. There is no macro language to expand, so
 * instantiating one is a verbatim copy of its text with the top-level `code:` changed,
 * `starter` taken off the top-level `tags:`, and every section the document carried named
 * under `requires:` instead. A document carries its connections and its schemas so that it
 * runs alone under `dg run --local`, and an instance refuses to store one that does, so a
 * copy names them. The teaching comments, the blank lines and the quoting are the point of
 * copying a document instead of generating one, so the edit is made at text level rather
 * than through a parser that would render the document afresh.
 *
 * IT IS `dirigent_cli.starters.instantiate`, TWICE. The CLI writes the copy into a project and
 * this writes it into the editor, and a reader who did both and got two different files would
 * be right to distrust whichever one they read second. The Python module and this one are the
 * same rules in the same order, and both suites assert the same cases.
 */

/** The tag a document opts into to say it may be copied, and the one a copy drops. */
export const STARTER_TAG = 'starter'

/** The sections a document may carry so that it runs alone, which a copy names instead. */
const CARRIED = ['connections', 'schemas'] as const

/** The top-level `code:` line: no indentation, so a step's own `code` is never touched. */
const CODE = /^code:[^\S\n]*(.*)$/mu

/** The top-level `tags:` line, and whatever it carries on the same line. */
const TAGS = /^tags:[^\S\n]*(.*)$/mu

/** One entry of a block list under `tags:`: indentation, a dash, the value. */
const TAG_ITEM = /^[^\S\n]*-[^\S\n]*(\S.*?)[^\S\n]*$/u

/** A mapping key on its own line: its indentation, its name, and what follows the colon. */
const KEY = /^([^\S\n]*)([^\s#][^:]*):[^\S\n]*(.*)$/u

/** One entry of an indented block list: its indentation, and the value. */
const ITEM = /^([^\S\n]+)-[^\S\n]+(\S.*?)[^\S\n]*$/u

/** Where a `requires:` section goes in a document that has none: after the first of these. */
const ANCHORS = ['tags', 'description', 'code'] as const

/** Copy a starter's text under a new code, naming what the original carried. */
export function instantiate(source: string, code: string): string {
    return uncarry(retag(recode(source, code)))
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

/** Take each carried section out and name the codes it held under `requires:`. */
function uncarry(source: string): string {
    let written = source
    for (const section of CARRIED) {
        const codes = carried(written, section)
        if (codes.length === 0) continue
        written = requireCodes(strip(written, section), section, codes)
    }
    return written
}

/** Where a top-level key sits, or `null` when the document has no such section. */
function top(lines: string[], name: string): number | null {
    for (const [index, line] of lines.entries()) {
        const matched = KEY.exec(line)
        if (matched !== null && matched[1] === '' && matched[2] === name) return index
    }
    return null
}

/**
 * What a top-level key owns: its comment run, its last line, and where it stops.
 *
 * The first index is the comment run written immediately above the key, the second is the
 * key's last indented line, and the third is the first line it does not own -- the next key,
 * or the comment run written above that key.
 */
function extent(lines: string[], at: number): { start: number; last: number; end: number } {
    let start = at
    while (start > 0 && (lines[start - 1] ?? '').startsWith('#')) start -= 1
    let last = at
    let end = at + 1
    while (end < lines.length) {
        const line = lines[end] ?? ''
        if (line.trim() !== '' && !/^\s/u.test(line)) break
        if (line.trim() !== '') last = end
        end += 1
    }
    return { start, last, end }
}

/** The codes a carried section holds, read from the keys one level under it. */
function carried(source: string, section: string): string[] {
    const lines = source.split('\n')
    const at = top(lines, section)
    if (at === null) return []
    const { last } = extent(lines, at)
    const codes: string[] = []
    let indent: string | null = null
    for (const line of lines.slice(at + 1, last + 1)) {
        const matched = KEY.exec(line)
        if (matched === null) continue
        indent ??= matched[1] ?? ''
        if ((matched[1] ?? '') === indent) codes.push((matched[2] ?? '').trim())
    }
    return codes
}

/** Remove a whole top-level section, the comment lines written above it included. */
function strip(source: string, section: string): string {
    const lines = source.split('\n')
    const at = top(lines, section)
    if (at === null) return source
    const { start, end } = extent(lines, at)
    return [...lines.slice(0, start), ...lines.slice(end)].join('\n')
}

/** Name each code under `requires:`, extending the list there or writing the section. */
function requireCodes(source: string, section: string, codes: string[]): string {
    const lines = source.split('\n')
    const at = top(lines, 'requires')
    if (at === null) return writeRequires(lines, section, codes)
    const { last } = extent(lines, at)
    const indent = indentOf(lines, at, last)
    for (let index = at + 1; index <= last; index += 1) {
        const matched = KEY.exec(lines[index] ?? '')
        if (matched !== null && (matched[1] ?? '') === indent && (matched[2] ?? '').trim() === section) {
            return extend(lines, index, section, codes)
        }
    }
    const written = entry(indent, section, codes)
    return [...lines.slice(0, last + 1), ...written, ...lines.slice(last + 1)].join('\n')
}

/** The indentation the keys under a section are written at, two spaces when it has none. */
function indentOf(lines: string[], at: number, last: number): string {
    for (const line of lines.slice(at + 1, last + 1)) {
        const matched = KEY.exec(line)
        if (matched !== null) return matched[1] ?? ''
    }
    return '  '
}

/** A section under `requires:`, written as a block list of the codes it names. */
function entry(indent: string, section: string, codes: string[]): string[] {
    return [`${indent}${section}:`, ...codes.map((code) => `${indent}${indent}- ${code}`)]
}

/** Add every code that is not already there to a list under `requires:`. */
function extend(lines: string[], at: number, section: string, codes: string[]): string {
    const matched = KEY.exec(lines[at] ?? '')
    const indent = matched === null ? '  ' : (matched[1] ?? '')
    const rest = matched === null ? '' : (matched[3] ?? '').trim()
    if (rest.startsWith('[')) {
        const inner = rest.replace(/^\[/u, '').replace(/\]$/u, '')
        const held = inner
            .split(',')
            .map((one) => one.trim())
            .filter((one) => one !== '')
        const listed = [...held, ...codes.filter((code) => !held.includes(code))]
        const copy = [...lines]
        copy[at] = `${indent}${section}: [${listed.join(', ')}]`
        return copy.join('\n')
    }
    if (rest !== '') return lines.join('\n')
    const items: { at: number; indent: string; value: string }[] = []
    for (let index = at + 1; index < lines.length; index += 1) {
        const found = ITEM.exec(lines[index] ?? '')
        if (found === null) break
        items.push({ at: index, indent: found[1] ?? '', value: found[2] ?? '' })
    }
    const held = new Set(items.map((item) => item.value))
    const itemIndent = items[0]?.indent ?? `${indent}${indent}`
    const written = codes.filter((code) => !held.has(code)).map((code) => `${itemIndent}- ${code}`)
    const after = items.length === 0 ? at + 1 : (items[items.length - 1]?.at ?? at) + 1
    return [...lines.slice(0, after), ...written, ...lines.slice(after)].join('\n')
}

/** Write the `requires:` a document has none of, under the header it follows. */
function writeRequires(lines: string[], section: string, codes: string[]): string {
    for (const name of ANCHORS) {
        const at = top(lines, name)
        if (at === null) continue
        const { end } = extent(lines, at)
        const before = end === 0 || (lines[end - 1] ?? '').trim() === '' ? [] : ['']
        const block = ['requires:', ...entry('  ', section, codes)]
        return [...lines.slice(0, end), ...before, ...block, '', ...lines.slice(end)].join('\n')
    }
    return lines.join('\n')
}
