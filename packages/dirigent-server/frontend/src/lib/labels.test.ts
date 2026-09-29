import { describe, expect, it } from 'vitest'

import { everyLabel, LABELS, type Label } from './labels'

/**
 * One rule held over the whole catalogue at once.
 *
 * This is what `Catalogue.all` buys on the server and what `everyLabel` buys here: a code that
 * cannot be typed, a label that says nothing, or a sentence that lost its value is caught by one
 * test over every string in the product rather than by whoever happens to read that screen.
 *
 * WHAT IS NOT TESTED HERE. That a label is the right words is review's job, and that no literal
 * was left in a component is `scripts/check_ui_labels.py`'s.
 */

/** A code segment: lowercase words joined by underscores, as the server's NAME_PATTERN is. */
const SEGMENT = /^[a-z][a-z0-9_]*$/

/** Call a sentence with one value per parameter, so its shape can be seen. */
function render(label: Label): string {
    if (typeof label === 'string') return label
    const values = Array.from({ length: label.length }, (_, at) => `v${String(at)}`)
    return (label as (...args: string[]) => string)(...values)
}

describe('the label catalogue', () => {
    const labels = [...everyLabel()]

    it('holds every section of LABELS', () => {
        expect(labels.length).toBeGreaterThan(Object.keys(LABELS).length)
        const sections = new Set(labels.map(([code]) => code.split('.')[0]))
        expect([...sections].sort()).toEqual(Object.keys(LABELS).sort())
    })

    it.each(labels)('%s is typed as a code', (code) => {
        for (const segment of code.split('.')) expect(segment).toMatch(SEGMENT)
    })

    // Not that it is trimmed: a label that joins two others -- ` and `, ` · updated ` -- carries
    // its own spacing, which is the half of the sentence a translation has to be able to move.
    it.each(labels)('%s says something', (_code, label) => {
        expect(render(label).trim()).not.toBe('')
    })

    it.each(labels.filter(([, label]) => typeof label === 'function'))(
        '%s writes every value it takes into what it says',
        (_code, label) => {
            const values = Array.from({ length: (label as (...args: string[]) => string).length })
            const said = render(label)
            values.forEach((_, at) => {
                expect(said).toContain(`v${String(at)}`)
            })
        },
    )

    it('renders a sentence around its value', () => {
        expect(LABELS.measure.ago('3m')).toBe('3m ago')
    })
})
