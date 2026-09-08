/**
 * What a picker offers and how what was typed narrows it.
 *
 * A ROW IS THE SAME PAIR EVERY LISTING DRAWS: the title a thing is read by, and the machine's
 * own half of it beside that -- a pipeline's code, a zone's offset. Both are searched, so the
 * row is found by whichever half somebody holds.
 */

/** One row of a picker: what it answers with, what it is titled by, and its machine half. */
export interface PickerOption {
    /** The value the picker answers with, which is the code or the identifier itself. */
    value: string
    /** What the row is titled by, which is a name where the thing has one. */
    label: string
    /** The machine's own half of the row, drawn in mono beside the title. Empty draws none. */
    aside: string
}

/**
 * Whether one row answers what was typed.
 *
 * EVERY TERM MATCHES, so typing more words narrows rather than widens, which is the rule the
 * command palette's own filter is written to.
 */
export function matchesOption(option: PickerOption, query: string): boolean {
    const terms = query.toLowerCase().split(/\s+/u).filter(Boolean)
    const read = `${option.label} ${option.aside}`.toLowerCase()
    return terms.every((term) => read.includes(term))
}
