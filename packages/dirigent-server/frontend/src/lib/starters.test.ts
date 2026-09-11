import { describe, expect, it } from 'vitest'

import { instantiate } from '@/lib/starters'

/**
 * The cases `packages/dirigent-cli/tests/test_starters.py` asserts, asserted again here.
 *
 * The CLI writes a copy into a project and this bundle writes one into the editor, and the two
 * must be the same file. Every case below is the same case that suite makes of the Python
 * module, so a rule that moves in one and not the other fails on both sides.
 */

const FLOW = `# A comment that has to survive.
format: dirigent/v1
kind: pipeline
code: a-starter
tags: [open-data, http, starter]

steps: {}
`

const BLOCK = `format: dirigent/v1
kind: pipeline
code: a-starter
tags:
  - open-data
  - starter
  - http

steps: {}
`

describe('instantiate', () => {
    it('rewrites the code and drops the starter tag from a flow list', () => {
        const copied = instantiate(FLOW, 'mine')
        expect(copied).toContain('code: mine')
        expect(copied).toContain('tags: [open-data, http]')
        expect(copied.startsWith('# A comment that has to survive.\n')).toBe(true)
    })

    it('drops the starter tag from a block list and keeps the rest in order', () => {
        const copied = instantiate(BLOCK, 'mine')
        expect(copied).toContain('code: mine')
        expect(copied).toContain('  - open-data\n  - http\n')
        expect(copied).not.toContain('starter')
    })

    it('takes the tag wherever it sits in the list', () => {
        for (const tags of ['[starter, a, b]', '[a, starter, b]', '[a, b, starter]']) {
            const copied = instantiate(FLOW.replace('[open-data, http, starter]', tags), 'mine')
            expect(copied).toContain('tags: [a, b]')
        }
        for (const block of ['  - starter\n  - a\n', '  - a\n  - starter\n']) {
            const copied = instantiate(BLOCK.replace('  - open-data\n  - starter\n  - http\n', block), 'mine')
            expect(copied).toContain('  - a\n')
            expect(copied).not.toContain('starter')
        }
    })

    it('drops the whole entry from a document whose only tag was starter', () => {
        expect(instantiate(FLOW.replace('[open-data, http, starter]', '[starter]'), 'mine')).not.toContain(
            'tags',
        )
        const onlyOne = BLOCK.replace('  - open-data\n  - starter\n  - http\n', '  - starter\n')
        const copied = instantiate(onlyOne, 'mine')
        expect(copied).not.toContain('tags')
        expect(copied.endsWith('steps: {}\n')).toBe(true)
    })

    it('never rewrites a step config key called code', () => {
        const source = FLOW.replace('steps: {}', 'steps:\n  one:\n    config:\n      code: keep-me\n')
        const copied = instantiate(source, 'mine')
        expect(copied).toContain('      code: keep-me')
        expect(copied).toContain('code: mine')
    })

    it('leaves a document with no tags entry alone but for its code', () => {
        const source = 'format: dirigent/v1\ncode: a-starter\nsteps: {}\n'
        expect(instantiate(source, 'mine')).toBe('format: dirigent/v1\ncode: mine\nsteps: {}\n')
    })
})
