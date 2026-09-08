import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

import { headingOf, oneLine, titleOf } from '@/lib/identity'

/** Everything under `src/`, which one test below reads to assert what is not in it. */
const SOURCE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

/** This file, which is excused from that read because it is the one holding the needle. */
const HERE = fileURLToPath(import.meta.url)

/** Every .ts and .tsx file under a directory, the generated shadcn primitives excepted. */
function everyFile(root: string): string[] {
    return readdirSync(root).flatMap((entry) => {
        const full = path.join(root, entry)
        if (statSync(full).isDirectory()) return entry === 'ui' ? [] : everyFile(full)
        if (full === HERE) return []
        return entry.endsWith('.ts') || entry.endsWith('.tsx') ? [full] : []
    })
}

/** The field the rename took away, which every entity now spells `name`. */
const GONE = 'display_name'

describe('what an addressable thing is called', () => {
    test('a name is the title and a thing with none is titled by its code', () => {
        expect(titleOf({ code: 'nightly-etl', name: 'Nightly ETL' })).toBe('Nightly ETL')
        expect(titleOf({ code: 'nightly-etl', name: null })).toBe('nightly-etl')
        expect(titleOf({ code: 'nightly-etl' })).toBe('nightly-etl')
    })

    test('a name of nothing but whitespace is no name', () => {
        expect(titleOf({ code: 'nightly-etl', name: '   ' })).toBe('nightly-etl')
        expect(titleOf({ code: 'nightly-etl', name: '' })).toBe('nightly-etl')
    })

    test('a name is trimmed, because what was typed around it is not part of it', () => {
        expect(titleOf({ code: 'nightly-etl', name: '  Nightly ETL  ' })).toBe('Nightly ETL')
    })

    test('the code goes under a title that is a name, and is not drawn twice when it is not', () => {
        expect(headingOf({ code: 'nightly-etl', name: 'Nightly ETL' })).toEqual({
            title: 'Nightly ETL',
            code: 'nightly-etl',
            named: true,
        })
        expect(headingOf({ code: 'nightly-etl', name: null })).toEqual({
            title: 'nightly-etl',
            code: null,
            named: false,
        })
    })

    test('a name spelled exactly as the code is the code, and is drawn once', () => {
        expect(headingOf({ code: 'nightly-etl', name: 'nightly-etl' })).toEqual({
            title: 'nightly-etl',
            code: null,
            named: false,
        })
    })
})

describe('a description as one line', () => {
    test('closes up every run of whitespace, so a paragraph fits a row', () => {
        expect(oneLine('  Reads the day  \nand forwards it.  ')).toBe('Reads the day and forwards it.')
    })

    test('sheds markdown markers rather than rendering or keeping them', () => {
        expect(oneLine('What this teaches is the **clock**, so `0 5 * * *` runs [here](https://x).')).toBe(
            'What this teaches is the clock, so 0 5 runs here.',
        )
    })
})

/**
 * DO NOT DELETE THIS TEST.
 *
 * An account's name used to be spelled differently from every other entity's, and the quartet
 * has one word for that field everywhere: `name`. A type or a fixture still carrying the old
 * spelling is a shape that no longer matches what the server sends, and it would read as
 * working right up until an account had a name.
 */
test('no type and no fixture still carries the field the rename took away', () => {
    const offenders = everyFile(SOURCE).filter((file) => readFileSync(file, 'utf8').includes(GONE))
    expect(offenders).toEqual([])
})

describe('a row says the opening', () => {
    test('the first sentence of the first paragraph, and nothing after it', () => {
        expect(oneLine('Echo a greeting. This is the smallest document.\n\nMore prose here.')).toBe('Echo a greeting.')
    })

    test('list markers go with the rest of the syntax', () => {
        expect(oneLine('- `shell.run` executes on the worker')).toBe('shell.run executes on the worker')
    })

    test('a description with no sentence end is shown whole', () => {
        expect(oneLine('everything the backend needs')).toBe('everything the backend needs')
    })
})
