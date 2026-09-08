import { describe, expect, test } from 'vitest'

import { applyFrame, initialState, type RunDetailState } from '@/lib/run-detail'
import type { DagNode, LogEntryOut, RunDetailOut, RunOut } from '@/lib/runs'
import {
    asNdjson,
    atLeast,
    clampTerminalHeight,
    copyText,
    countLines,
    downloadName,
    emptyNote,
    endNote,
    EVERY_LINE,
    fieldsText,
    LEVELS,
    lineCount,
    lineSpan,
    narrowed,
    setTerminalHeight,
    stepChoices,
    stepOf,
    terminalHeight,
    TERMINAL_MAX_HEIGHT,
    TERMINAL_MIN_HEIGHT,
    visibleLines,
    type LineFilters,
} from '@/lib/terminal'

function run(over: Partial<RunOut> = {}): RunOut {
    return {
        id: 'r-1',
        pipeline: 'nightly',
        pipeline_version: 3,
        priority: 'normal',
        status: 'running',
        params: {},
        triggered_by_kind: 'user',
        triggered_by_label: 'dev',
        trace_id: 'trace-1',
        error: null,
        failed_step: null,
        started_at: '2026-03-01T11:59:00Z',
        finished_at: null,
        window_start: null,
        window_end: null,
        created_at: '2026-03-01T11:58:00Z',
        ...over,
    }
}

function node(code: string): DagNode {
    return {
        code,
        name: null,
        block: 'transform.jq',
        outcome: 'pending',
        depends_on: [],
        rule: 'all_success',
        fan_out: false,
        items_total: 0,
        items_failed: 0,
        attempts: 0,
    }
}

function detail(names: string[] = ['fetch', 'shape']): RunDetailOut {
    return {
        run: run(),
        dag: { nodes: names.map((name) => node(name)), edges: [] },
        items_total: 0,
        attempts_total: 0,
        waiting_for_workers: null,
    }
}

function entry(over: Partial<LogEntryOut> = {}): LogEntryOut {
    return {
        id: 1,
        run_id: 'r-1',
        step_name: 'fetch',
        step_attempt_id: 'a-1',
        level: 'info',
        message: 'reaching out',
        fields: null,
        created_at: '2026-03-01T11:59:11Z',
        ...over,
    }
}

/** A run's state with these lines already delivered, in the order they are named. */
function withLines(entries: LogEntryOut[], names?: string[]): RunDetailState {
    return entries.reduce(
        (state, one) => applyFrame(state, { kind: 'log', entry: one }),
        initialState(detail(names)),
    )
}

/** A run with no fan-out anywhere, which is what most of these cases are about. */
const NO_ITEMS = new Map<string, string>()

/** Two steps writing turn about, which is what a run of anything actually looks like. */
const INTERLEAVED: LogEntryOut[] = [
    entry({ id: 1, step_name: 'fetch', level: 'info', message: 'reaching out' }),
    entry({ id: 2, step_name: 'shape', level: 'debug', message: 'program compiled' }),
    entry({ id: 3, step_name: 'fetch', level: 'warning', message: 'retrying once' }),
    entry({ id: 4, step_name: 'shape', level: 'error', message: 'the program refused a null' }),
    entry({ id: 5, step_name: null, level: 'info', message: 'run finished' }),
]

describe('a level threshold', () => {
    test('lets a line through at the threshold and above it', () => {
        expect(atLeast('warning', 'info')).toBe(true)
        expect(atLeast('warning', 'warning')).toBe(true)
        expect(atLeast('error', 'warning')).toBe(true)
    })

    test('holds a line back below it', () => {
        expect(atLeast('debug', 'info')).toBe(false)
        expect(atLeast('info', 'error')).toBe(false)
    })

    test('shows a level this bundle was built before rather than hiding it', () => {
        // A line nobody can read is worse than a line below the threshold.
        expect(atLeast('fatal', 'error')).toBe(true)
    })

    test('is every level at its quietest, which is where the drawer opens', () => {
        expect(EVERY_LINE.level).toBe(LEVELS[0])
        expect(LEVELS.every((level) => atLeast(level, 'debug'))).toBe(true)
    })
})

describe('the lines the drawer draws', () => {
    const state = withLines(INTERLEAVED)

    test('are every step interleaved, in the order the run wrote them', () => {
        const shown = visibleLines(state.logs, EVERY_LINE, NO_ITEMS)
        expect(shown.map((line) => line.id)).toEqual([1, 2, 3, 4, 5])
        expect(shown.map((line) => line.step_name)).toEqual(['fetch', 'shape', 'fetch', 'shape', null])
    })

    test('keep arrival order however the run interleaved them', () => {
        // The reducer appends, so the drawer's order is the stream's order and nothing else.
        const shuffled = withLines([
            entry({ id: 10, step_name: 'shape', message: 'second' }),
            entry({ id: 11, step_name: 'fetch', message: 'third' }),
            entry({ id: 12, step_name: 'shape', message: 'fourth' }),
        ])
        expect(visibleLines(shuffled.logs, EVERY_LINE, NO_ITEMS).map((line) => line.message)).toEqual([
            'second',
            'third',
            'fourth',
        ])
    })

    test('narrow to one level threshold', () => {
        const shown = visibleLines(state.logs, { ...EVERY_LINE, level: 'warning' }, NO_ITEMS)
        expect(shown.map((line) => line.id)).toEqual([3, 4])
    })

    test('narrow to one step, leaving the run-level lines out of it', () => {
        const shown = visibleLines(state.logs, { ...EVERY_LINE, step: 'shape' }, NO_ITEMS)
        expect(shown.map((line) => line.id)).toEqual([2, 4])
    })

    test('narrow to what a line says, without case', () => {
        expect(visibleLines(state.logs, { ...EVERY_LINE, match: 'REFUSED' }, NO_ITEMS).map((line) => line.id)).toEqual([4])
    })

    test('match a step name and a field as well as a message', () => {
        const held = withLines([
            entry({ id: 20, step_name: 'archive', message: 'copied', fields: { uri: 'file:///cold.json' } }),
            entry({ id: 21, step_name: 'report', message: 'done', fields: null }),
        ])
        expect(visibleLines(held.logs, { ...EVERY_LINE, match: 'cold.json' }, NO_ITEMS).map((line) => line.id)).toEqual([20])
        expect(visibleLines(held.logs, { ...EVERY_LINE, match: 'archive' }, NO_ITEMS).map((line) => line.id)).toEqual([20])
    })

    test('match the item label the pane draws on the line', () => {
        // The label is joined on by the renderer, so a search that did not read it would answer
        // "no lines" about a label the reader is looking straight at.
        const held = withLines([
            entry({ id: 30, step_name: 'fetch', step_attempt_id: 'a-north', message: 'http call' }),
            entry({ id: 31, step_name: 'fetch', step_attempt_id: 'a-south', message: 'http call' }),
        ])
        const labels = new Map([
            ['a-north', 'north'],
            ['a-south', 'south'],
        ])
        expect(visibleLines(held.logs, { ...EVERY_LINE, match: 'north' }, labels).map((line) => line.id)).toEqual([30])
        expect(visibleLines(held.logs, { ...EVERY_LINE, match: 'north' }, NO_ITEMS)).toEqual([])
    })

    test('compose: all three hold at once', () => {
        const filters: LineFilters = { level: 'warning', step: 'fetch', match: 'retry' }
        expect(visibleLines(state.logs, filters, NO_ITEMS).map((line) => line.id)).toEqual([3])
    })

    test('compose to nothing where the three disagree', () => {
        // The one error came from shape, so asking for fetch's errors is an empty answer rather
        // than the nearest one.
        expect(visibleLines(state.logs, { level: 'error', step: 'fetch', match: '' }, NO_ITEMS)).toEqual([])
    })

    test('ignore the whitespace somebody typed either side of a match', () => {
        expect(visibleLines(state.logs, { ...EVERY_LINE, match: '  retrying  ' }, NO_ITEMS).map((line) => line.id)).toEqual([3])
    })
})

describe('what the count line says', () => {
    test('is how much of what is held is on screen', () => {
        const state = withLines(INTERLEAVED)
        const shown = visibleLines(state.logs, { ...EVERY_LINE, level: 'warning' }, NO_ITEMS)
        expect(lineCount(shown.length, state.logs.length)).toBe('2 of 5 lines')
    })

    test('says line rather than lines where there is one', () => {
        expect(lineCount(1, 1)).toBe('1 of 1 line')
    })

    test('says nothing at all where the run has written no line to count', () => {
        expect(lineCount(0, 0)).toBeNull()
    })
})

describe('how many lines a set of entries draws', () => {
    // REVERT-PROOF against a counter that counted entries: a stack trace is one entry and
    // many lines, and "42 of 42 lines" over a two-hundred-line log is a count of the wrong thing.
    test('counts the lines a message carries rather than the entries carrying them', () => {
        expect(lineSpan(entry({ message: 'one line' }))).toBe(1)
        expect(lineSpan(entry({ message: 'Traceback:\n  file.py, line 3\nValueError' }))).toBe(3)
    })

    test('counts the fields drawn after a message as part of the same reading', () => {
        expect(lineSpan(entry({ message: 'saved', fields: { note: 'first\nsecond' } }))).toBe(2)
    })

    test('an entry that said nothing at all still occupies the line it is drawn on', () => {
        expect(lineSpan(entry({ message: '' }))).toBe(1)
    })

    test('adds up over the entries, which is what the count line states', () => {
        const entries = [entry({ id: 1, message: 'a\nb\nc' }), entry({ id: 2, message: 'd' })]
        expect(countLines(entries)).toBe(4)
        expect(countLines([])).toBe(0)
        expect(lineCount(countLines(entries), countLines(entries))).toBe('4 of 4 lines')
    })
})

describe('what an empty drawer says', () => {
    test('states the fact when the run has written nothing', () => {
        expect(emptyNote(EVERY_LINE, 0)).toBe('Nothing logged.')
    })

    test('states the filters as the fact where they are what emptied it', () => {
        expect(emptyNote({ ...EVERY_LINE, level: 'error' }, 12)).toBe('No line matches these filters.')
    })

    test('does not claim a filtered run wrote nothing', () => {
        // "Nothing logged" in front of somebody who filtered to errors is a lie about the run.
        expect(emptyNote({ ...EVERY_LINE, step: 'fetch' }, 0)).not.toMatch(/Nothing logged/)
    })

    test('knows whether anything was asked of it', () => {
        expect(narrowed(EVERY_LINE)).toBe(false)
        expect(narrowed({ ...EVERY_LINE, match: 'x' })).toBe(true)
        expect(narrowed({ ...EVERY_LINE, step: 'fetch' })).toBe(true)
        expect(narrowed({ ...EVERY_LINE, level: 'info' })).toBe(true)
    })
})

describe("a line's step prefix", () => {
    test('names the step to open', () => {
        expect(stepOf(entry({ step_name: 'shape' }))).toBe('shape')
    })

    test('opens nothing where no step wrote the line', () => {
        // The engine's own lines belong to no step, so their prefix is a label, not a control.
        expect(stepOf(entry({ step_name: null }))).toBeNull()
        expect(stepOf(entry({ step_name: '' }))).toBeNull()
    })

    test('maps every line of a run to the step the panel would open', () => {
        const state = withLines(INTERLEAVED)
        expect(visibleLines(state.logs, EVERY_LINE, NO_ITEMS).map((line) => stepOf(line))).toEqual([
            'fetch',
            'shape',
            'fetch',
            'shape',
            null,
        ])
    })
})

describe('the step select', () => {
    test('offers every step of the run graph, in the order it was laid out', () => {
        expect(stepChoices(withLines([], ['parse', 'active', 'report']))).toEqual(['parse', 'active', 'report'])
    })

    test('offers a step that has written nothing, because somebody may be looking for it', () => {
        const state = withLines([entry({ step_name: 'parse' })], ['parse', 'report'])
        expect(stepChoices(state)).toContain('report')
    })
})

describe("a line's fields", () => {
    test('are nothing where a line carries none', () => {
        expect(fieldsText(null)).toBeNull()
        expect(fieldsText({})).toBeNull()
    })

    test('read as key=value, a string unquoted and everything else as JSON', () => {
        expect(fieldsText({ uri: 'file:///a.json', bytes: 12, ok: true })).toBe('uri=file:///a.json bytes=12 ok=true')
    })
})

describe('copying and saving', () => {
    test('copies the lines on screen, one per line, with what each says beside it', () => {
        const state = withLines(INTERLEAVED)
        const text = copyText(visibleLines(state.logs, { ...EVERY_LINE, level: 'error' }, NO_ITEMS))
        expect(text.split('\n')).toHaveLength(1)
        expect(text).toContain('the program refused a null')
        expect(text).toContain('shape')
    })

    test('writes NDJSON as one entry per line, exactly as the API answered it', () => {
        const lines = asNdjson(INTERLEAVED).split('\n')
        expect(lines).toHaveLength(INTERLEAVED.length)
        expect(JSON.parse(lines[0] ?? '')).toEqual(INTERLEAVED[0])
    })

    test('names the file after the run it came from', () => {
        expect(downloadName('r-1')).toBe('dirigent-run-r-1.ndjson')
    })
})

describe("the drawer's height", () => {
    test('is kept as the pixels somebody dragged it to', () => {
        expect(clampTerminalHeight(313)).toBe(313)
    })

    test('rounds to whole pixels, because a pointer reports fractions and a layout does not', () => {
        expect(clampTerminalHeight(312.6)).toBe(313)
    })

    test('stops at a height that is still a console rather than a header', () => {
        expect(clampTerminalHeight(10)).toBe(TERMINAL_MIN_HEIGHT)
    })

    test('stops before the console becomes the screen the graph was on', () => {
        expect(clampTerminalHeight(4000)).toBe(TERMINAL_MAX_HEIGHT)
    })

    test('keeps the dragged height and clamps what it stores', () => {
        setTerminalHeight(9000)
        expect(terminalHeight.get()).toBe(TERMINAL_MAX_HEIGHT)
        setTerminalHeight(320)
        expect(terminalHeight.get()).toBe(320)
    })
})

describe('the line the console ends on', () => {
    test('states the outcome in the run\'s own word', () => {
        expect(endNote('succeeded')).toBe('run succeeded')
        expect(endNote('failed')).toBe('run failed')
        expect(endNote('completed_with_errors')).toBe('run completed with errors')
    })

    test('says the log ended when the outcome is not at hand', () => {
        expect(endNote(null)).toBe('end of log')
        expect(endNote('running')).toBe('end of log')
    })
})
