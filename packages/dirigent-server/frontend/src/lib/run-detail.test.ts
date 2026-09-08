import { describe, expect, test } from 'vitest'

import {
    ITEM_STRIP_LIMIT,
    MAX_LOG_LINES,
    applyFrame,
    attemptOrder,
    attemptsForStep,
    decodeFrame,
    durationOf,
    queuedOf,
    readsAsTheWholeStep,
    waitingOf,
    drawnStates,
    edgeClasses,
    edgeMotion,
    edgeTone,
    handovers,
    initialState,
    itemLabels,
    itemOfEntry,
    itemOutputs,
    itemStrip,
    nodeTone,
    logsForStep,
    outcomeOf,
    outputReading,
    reduce,
    resumeCursor,
    retryStory,
    stepViews,
    toleratedFanOut,
    withStream,
    type RunDetailState,
    type StepView,
} from '@/lib/run-detail'
import { headingOf } from '@/lib/identity'
import type { AttemptEvent, DagNode, LogEntryOut, RunDetailOut, RunOut } from '@/lib/runs'
import type { AttemptStatus, RunStatus } from '@/lib/status'

const NOW = Date.parse('2026-03-01T12:00:00Z')

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

function node(over: Partial<DagNode> = {}): DagNode {
    return {
        code: 'fetch',
        name: null,
        block: 'http.request',
        outcome: 'pending',
        depends_on: [],
        rule: 'all_success',
        fan_out: false,
        items_total: 0,
        items_failed: 0,
        attempts: 0,
        ...over,
    }
}

function attempt(over: Partial<AttemptEvent> = {}): AttemptEvent {
    // An element's id stands in for its label, which is the ordinary case. A test that means to
    // tell the two apart names `run_item_id` itself.
    const item = over.item ?? null
    return {
        id: 'a-1',
        step_name: 'fetch',
        block_id: 'http.request',
        attempt: 1,
        kind: 'automatic',
        status: 'running',
        run_item_id: item === null ? null : `item-${item}`,
        error: null,
        error_class: null,
        output: null,
        output_uri: null,
        output_bytes: null,
        waiting_message: null,
        waiting_progress: null,
        poke_count: 0,
        next_poll_at: null,
        available_at: null,
        deadline_at: null,
        heartbeat_at: null,
        started_at: '2026-03-01T11:59:10Z',
        finished_at: null,
        created_at: '2026-03-01T11:59:00Z',
        item: null,
        item_index: null,
        ...over,
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

function detail(over: Partial<RunDetailOut> = {}): RunDetailOut {
    return {
        run: run(),
        dag: { nodes: [node()], edges: [] },
        items_total: 0,
        attempts_total: 0,
        waiting_for_workers: null,
        ...over,
    }
}

/** One node as the graph draws it, which is what every colour decision is made from. */
function drawn(over: Partial<StepView> = {}): StepView {
    return {
        node: node(),
        outcome: 'pending',
        attempts: [],
        latest: null,
        detail: null,
        duration_ms: null,
        queued_ms: null,
        waiting_ms: null,
        strip: { kind: 'empty' },
        ...over,
    }
}

/** A state with the given attempts already applied, in the order they are named. */
function fed(attempts: AttemptEvent[], base: RunDetailState = initialState(detail())): RunDetailState {
    return attempts.reduce((state, one) => applyFrame(state, { kind: 'attempt', attempt: one }), base)
}

describe('reading a frame off the stream', () => {
    test('names each of the four the server sends', () => {
        expect(decodeFrame({ event: 'attempt', data: JSON.stringify(attempt()), id: null }).kind).toBe('attempt')
        expect(decodeFrame({ event: 'log', data: JSON.stringify(entry()), id: '7' }).kind).toBe('log')
        expect(decodeFrame({ event: 'run', data: JSON.stringify(run()), id: null }).kind).toBe('run')
        expect(decodeFrame({ event: 'end', data: '{}', id: null }).kind).toBe('end')
    })

    test('turns a payload that does not parse into an unknown frame rather than throwing', () => {
        // A long-lived stream must survive one bad line; the screen is open for the whole run.
        expect(decodeFrame({ event: 'log', data: 'not json', id: null })).toEqual({
            kind: 'unknown',
            event: 'log',
        })
    })

    test('drops an event this bundle was built before, rather than guessing at it', () => {
        expect(decodeFrame({ event: 'heartbeat', data: '{}', id: null }).kind).toBe('unknown')
    })
})

describe('the connect replay', () => {
    // THE REVERT-PROOF ONE. The server reports every attempt again on every connect, on purpose:
    // attempt frames carry no id and cannot be resumed past. Break the dedupe in `applyFrame`
    // -- drop the fingerprint comparison, or key `attempts` by anything but the attempt's own id
    // -- and this test fails, because a replayed frame would build a new state object.
    test('is idempotent by reference: replaying the same attempts changes nothing at all', () => {
        const first = attempt({ id: 'a-1', status: 'succeeded', finished_at: '2026-03-01T11:59:20Z' })
        const second = attempt({ id: 'a-2', step_name: 'archive', status: 'running' })
        const settledOnce = fed([first, second])

        const replayed = fed([first, second], settledOnce)

        expect(replayed).toBe(settledOnce)
        expect(Object.keys(replayed.attempts)).toEqual(['a-1', 'a-2'])
        expect(replayed.order).toEqual(['a-1', 'a-2'])
    })

    test('dedupes by the attempt id, so the same attempt twice is one attempt', () => {
        const state = fed([attempt({ id: 'a-1' }), attempt({ id: 'a-1' })])
        expect(attemptsForStep(state, 'fetch')).toHaveLength(1)
    })

    test('keeps the order attempts were first seen in, whatever order they are replayed in', () => {
        const one = attempt({ id: 'a-1' })
        const two = attempt({ id: 'a-2', step_name: 'archive' })
        const state = fed([two, one])
        expect(state.order).toEqual(['a-2', 'a-1'])
    })
})

describe('an attempt that moved', () => {
    test('supersedes the state the stream reported for it before', () => {
        const running = attempt({ id: 'a-1', status: 'running' })
        const done = attempt({ id: 'a-1', status: 'succeeded', finished_at: '2026-03-01T11:59:30Z' })
        const state = fed([running, done])

        expect(state.attempts['a-1']?.status).toBe('succeeded')
        expect(state.order).toEqual(['a-1'])
    })

    test('is news when only its waiting message changed, because that is what a poll says', () => {
        const waiting = attempt({ id: 'a-1', status: 'waiting', waiting_message: 'queued at the remote' })
        const later = attempt({ id: 'a-1', status: 'waiting', waiting_message: 'running at the remote' })
        const state = fed([waiting, later])
        expect(state.attempts['a-1']?.waiting_message).toBe('running at the remote')
    })

    test('does not move a settled attempt back to a live one, however late the frame is', () => {
        const done = attempt({ id: 'a-1', status: 'failed', error: 'the remote refused' })
        const stale = attempt({ id: 'a-1', status: 'running', error: null })
        const state = fed([done, stale])

        expect(state.attempts['a-1']?.status).toBe('failed')
        expect(state.attempts['a-1']?.error).toBe('the remote refused')
    })

    test('does not let an earlier try overwrite a later one under the same id', () => {
        const second = attempt({ id: 'a-1', attempt: 2, status: 'running' })
        const first = attempt({ id: 'a-1', attempt: 1, status: 'running', started_at: '2026-03-01T11:00:00Z' })
        const state = fed([second, first])
        expect(state.attempts['a-1']?.attempt).toBe(2)
    })
})

describe('a log frame', () => {
    test('appends, and moves the cursor a reconnect resumes past', () => {
        let state = initialState(detail())
        state = applyFrame(state, { kind: 'log', entry: entry({ id: 4 }) })
        state = applyFrame(state, { kind: 'log', entry: entry({ id: 9, message: 'done' }) })

        expect(state.logs.map((one) => one.id)).toEqual([4, 9])
        expect(resumeCursor(state)).toBe('9')
    })

    test('is dropped when the stream repeats an id already applied', () => {
        let state = applyFrame(initialState(detail()), { kind: 'log', entry: entry({ id: 4 }) })
        const before = state
        state = applyFrame(state, { kind: 'log', entry: entry({ id: 4 }) })
        expect(state).toBe(before)
    })

    test('filters to the step that wrote it, which is how one stream fills a step pane', () => {
        let state = initialState(detail())
        state = applyFrame(state, { kind: 'log', entry: entry({ id: 1, step_name: 'fetch', message: 'a' }) })
        state = applyFrame(state, { kind: 'log', entry: entry({ id: 2, step_name: 'archive', message: 'b' }) })
        state = applyFrame(state, { kind: 'log', entry: entry({ id: 3, step_name: null, message: 'c' }) })

        expect(logsForStep(state.logs, 'fetch').map((one) => one.message)).toEqual(['a'])
        expect(logsForStep(state.logs, 'archive').map((one) => one.message)).toEqual(['b'])
    })

    test('holds a tail rather than the whole of a long run', () => {
        let state = initialState(detail())
        for (let id = 1; id <= MAX_LOG_LINES + 10; id += 1) {
            state = applyFrame(state, { kind: 'log', entry: entry({ id }) })
        }
        expect(state.logs).toHaveLength(MAX_LOG_LINES)
        expect(state.logs[0]?.id).toBe(11)
        expect(resumeCursor(state)).toBe(String(MAX_LOG_LINES + 10))
    })

    test('leaves the cursor unset before the stream has stated an id', () => {
        expect(resumeCursor(initialState(detail()))).toBeNull()
    })
})

describe('the run frame', () => {
    test('replaces the run when it says something new', () => {
        const state = applyFrame(initialState(detail()), {
            kind: 'run',
            run: run({ status: 'succeeded', finished_at: '2026-03-01T12:00:00Z' }),
        })
        expect(state.run.status).toBe('succeeded')
    })

    test('does not move a settled run back to a live one', () => {
        let state = applyFrame(initialState(detail()), { kind: 'run', run: run({ status: 'failed' }) })
        state = applyFrame(state, { kind: 'run', run: run({ status: 'running' }) })
        expect(state.run.status).toBe('failed')
    })

    test('takes a queued run to running, with the start time the header shows', () => {
        const queued = initialState(detail({ run: run({ status: 'queued', started_at: null }) }))
        const state = applyFrame(queued, {
            kind: 'run',
            run: run({ status: 'running', started_at: '2026-03-01T11:59:00Z' }),
        })
        expect(state.run.status).toBe('running')
        expect(state.run.started_at).toBe('2026-03-01T11:59:00Z')
    })

    test('takes a start time that arrives on its own', () => {
        const state = applyFrame(initialState(detail({ run: run({ started_at: null }) })), {
            kind: 'run',
            run: run({ started_at: '2026-03-01T11:59:00Z' }),
        })
        expect(state.run.started_at).toBe('2026-03-01T11:59:00Z')
    })

    test('changes nothing when it repeats what the state already holds', () => {
        const settled = applyFrame(initialState(detail()), { kind: 'run', run: run({ status: 'cancelled' }) })
        expect(applyFrame(settled, { kind: 'run', run: run({ status: 'cancelled' }) })).toBe(settled)
    })
})

describe('the end frame', () => {
    test('closes the stream state', () => {
        const state = applyFrame(initialState(detail()), { kind: 'end' })
        expect(state.stream).toBe('ended')
    })

    test('changes nothing when the stream is already closed', () => {
        const closed = applyFrame(initialState(detail()), { kind: 'end' })
        expect(applyFrame(closed, { kind: 'end' })).toBe(closed)
    })

    test('leaves everything the stream delivered exactly where it was', () => {
        const before = fed([attempt({ id: 'a-1', status: 'succeeded' })])
        const after = applyFrame(before, { kind: 'end' })
        expect(after.attempts).toBe(before.attempts)
        expect(after.logs).toBe(before.logs)
    })
})

describe('the stream state', () => {
    test('is set without disturbing what has been delivered', () => {
        const before = fed([attempt()])
        const after = withStream(before, 'reconnecting')
        expect(after.stream).toBe('reconnecting')
        expect(after.attempts).toBe(before.attempts)
    })

    test('publishes nothing when it is already what it is being set to', () => {
        const before = withStream(initialState(detail()), 'live')
        expect(withStream(before, 'live')).toBe(before)
    })
})

describe('the screen reducer', () => {
    test('drops every frame until the initial read has landed', () => {
        expect(reduce(null, { kind: 'frame', frame: { kind: 'end' } })).toBeNull()
        expect(reduce(null, { kind: 'stream', stream: 'live' })).toBeNull()
    })

    test('starts over on a read, which is what opening a different run is', () => {
        const first = reduce(null, { kind: 'loaded', detail: detail() })
        const fedFirst = reduce(first, { kind: 'frame', frame: { kind: 'log', entry: entry({ id: 3 }) } })
        const second = reduce(fedFirst, { kind: 'loaded', detail: detail({ run: run({ id: 'r-2' }) }) })

        expect(second?.run.id).toBe('r-2')
        expect(second?.logs).toEqual([])
        expect(second?.lastLogId).toBeNull()
    })

    test('empties on a reset, so no cursor of the run somebody left survives it', () => {
        const first = reduce(null, { kind: 'loaded', detail: detail() })
        const fedFirst = reduce(first, { kind: 'frame', frame: { kind: 'log', entry: entry({ id: 42 }) } })
        expect(fedFirst === null ? null : resumeCursor(fedFirst)).toBe('42')

        expect(reduce(fedFirst, { kind: 'reset' })).toBeNull()
    })

    test('drops the frames of the run somebody left until the next run has been read', () => {
        const first = reduce(null, { kind: 'loaded', detail: detail() })
        const empty = reduce(first, { kind: 'reset' })

        expect(reduce(empty, { kind: 'frame', frame: { kind: 'log', entry: entry({ id: 42 }) } })).toBeNull()
        expect(reduce(empty, { kind: 'frame', frame: { kind: 'run', run: run({ status: 'succeeded' }) } })).toBeNull()
        expect(reduce(empty, { kind: 'stream', stream: 'live' })).toBeNull()

        const second = reduce(empty, { kind: 'loaded', detail: detail({ run: run({ id: 'r-2' }) }) })
        expect(second?.run.id).toBe('r-2')
        expect(second === null ? 'unset' : resumeCursor(second)).toBeNull()

        const fedSecond = reduce(second, { kind: 'frame', frame: { kind: 'log', entry: entry({ id: 7 }) } })
        expect(fedSecond?.logs.map((one) => one.id)).toEqual([7])
    })
})

describe('what a step amounts to', () => {
    test('is the graph outcome the initial read stated until an attempt says otherwise', () => {
        expect(outcomeOf([], 'skipped')).toBe('skipped')
    })

    test('is running while anything is still moving, even beside a failed element', () => {
        const attempts = [
            attempt({ id: 'a-1', item: 'east', status: 'failed' }),
            attempt({ id: 'a-2', item: 'west', status: 'running' }),
        ]
        expect(outcomeOf(attempts, 'pending')).toBe('running')
    })

    test('is failed once nothing is left that could still succeed', () => {
        const attempts = [
            attempt({ id: 'a-1', item: 'east', status: 'failed' }),
            attempt({ id: 'a-2', item: 'west', status: 'succeeded' }),
        ]
        expect(outcomeOf(attempts, 'pending')).toBe('failed')
    })

    test('is pending only while every element still is', () => {
        const waiting = [attempt({ id: 'a-1', item: 'east', status: 'pending' })]
        expect(outcomeOf(waiting, 'running')).toBe('pending')

        const started = [...waiting, attempt({ id: 'a-2', item: 'west', status: 'succeeded' })]
        expect(outcomeOf(started, 'running')).toBe('running')
    })

    test('is skipped only when every element was', () => {
        expect(outcomeOf([attempt({ status: 'skipped' })], 'pending')).toBe('skipped')
    })

    test('tells two elements with the same label apart, so neither hides behind the other', () => {
        const attempts = [
            attempt({ id: 'a-1', run_item_id: 'item-1', item: 'oslo', status: 'succeeded' }),
            attempt({ id: 'a-2', run_item_id: 'item-2', item: 'oslo', status: 'running' }),
        ]
        expect(outcomeOf(attempts, 'pending')).toBe('running')
    })

    test('reads the latest try of an element rather than its first', () => {
        const attempts = [
            attempt({ id: 'a-1', attempt: 1, status: 'failed', item: 'east' }),
            attempt({ id: 'a-2', attempt: 2, status: 'succeeded', item: 'east' }),
        ]
        expect(outcomeOf(attempts, 'pending')).toBe('succeeded')
    })
})

describe("a fan-out step's item strip", () => {
    /** `count` elements, each in the state the caller names. */
    function elements(count: number, status: AttemptStatus = 'succeeded'): AttemptEvent[] {
        return Array.from({ length: count }, (_, index) =>
            attempt({ id: `a-${String(index)}`, item: `region-${String(index)}`, status }),
        )
    }

    test('names the elements while there are few enough to name', () => {
        const strip = itemStrip(elements(ITEM_STRIP_LIMIT), NOW)
        expect(strip.kind).toBe('chips')
        if (strip.kind !== 'chips') return
        expect(strip.items).toHaveLength(ITEM_STRIP_LIMIT)
        expect(strip.items[0]).toEqual({ id: 'item-region-0', key: 'region-0', status: 'succeeded', retry: null })
    })

    test('counts them instead the moment there is one more than fits', () => {
        const strip = itemStrip(elements(ITEM_STRIP_LIMIT + 1), NOW)
        expect(strip.kind).toBe('counts')
        if (strip.kind !== 'counts') return
        expect(strip.total).toBe(ITEM_STRIP_LIMIT + 1)
        expect(strip.counts).toEqual([{ status: 'succeeded', count: ITEM_STRIP_LIMIT + 1 }])
    })

    test('counts each state separately, which is the whole point of counting', () => {
        const mixed = [
            ...elements(12, 'succeeded'),
            attempt({ id: 'x-1', item: 'bad', status: 'failed' }),
            attempt({ id: 'x-2', item: 'slow', status: 'running' }),
            attempt({ id: 'x-3', item: 'slower', status: 'running' }),
            attempt({ id: 'x-4', item: 'slowest', status: 'running' }),
        ]
        const strip = itemStrip(mixed, NOW)
        expect(strip.kind).toBe('counts')
        if (strip.kind !== 'counts') return
        expect(strip.total).toBe(16)
        expect(new Map(strip.counts.map((one) => [one.status, one.count]))).toEqual(
            new Map([
                ['succeeded', 12],
                ['failed', 1],
                ['running', 3],
            ]),
        )
    })

    test('is one entry per element however many tries it took, and says how many', () => {
        const retried = [
            attempt({ id: 'a-1', item: 'east', attempt: 1, status: 'failed' }),
            attempt({ id: 'a-2', item: 'east', attempt: 2, status: 'succeeded' }),
        ]
        const strip = itemStrip(retried, NOW)
        expect(strip.kind).toBe('chips')
        if (strip.kind !== 'chips') return
        expect(strip.items).toEqual([{ id: 'item-east', key: 'east', status: 'succeeded', retry: 'try 2' }])
    })

    test('draws two elements that share a label as the two elements they are', () => {
        const strip = itemStrip(
            [
                attempt({ id: 'a-1', run_item_id: 'item-1', item: 'oslo', status: 'succeeded' }),
                attempt({ id: 'a-2', run_item_id: 'item-2', item: 'oslo', status: 'running' }),
            ],
            NOW,
        )
        expect(strip.kind).toBe('chips')
        if (strip.kind !== 'chips') return
        expect(strip.items).toEqual([
            { id: 'item-1', key: 'oslo', status: 'succeeded', retry: null },
            { id: 'item-2', key: 'oslo', status: 'running', retry: null },
        ])
    })

    test('is empty before the stream has reported anything of the step', () => {
        expect(itemStrip([], NOW).kind).toBe('empty')
    })

    test('takes the threshold from its caller, so a wider node can name more', () => {
        expect(itemStrip(elements(8), NOW, 10).kind).toBe('chips')
    })
})

describe("a retrying element's story", () => {
    test('is nothing on a first try', () => {
        expect(retryStory(attempt({ attempt: 1 }), NOW)).toBeNull()
    })

    test('says which try it is, and how long until the next poll', () => {
        const due = new Date(NOW + 8000).toISOString()
        expect(retryStory(attempt({ attempt: 2, next_poll_at: due }), NOW)).toBe('try 2 in 8s')
    })

    test('says only which try it is once the poll is due', () => {
        const passed = new Date(NOW - 1000).toISOString()
        expect(retryStory(attempt({ attempt: 3, next_poll_at: passed }), NOW)).toBe('try 3')
    })

    test('says only which try it is when nothing is scheduled', () => {
        expect(retryStory(attempt({ attempt: 2, next_poll_at: null }), NOW)).toBe('try 2')
    })
})

describe('the nodes the graph draws', () => {
    const dag = {
        nodes: [node({ code: 'fetch' }), node({ code: 'push', fan_out: true, items_total: 3, depends_on: ['fetch'] })],
        edges: [['fetch', 'push']] as [string, string][],
    }

    test('carries every step the pinned definition had, in the order the API laid them out', () => {
        const views = stepViews(initialState(detail({ dag })), NOW)
        expect(views.map((view) => view.node.code)).toEqual(['fetch', 'push'])
    })

    test('folds the stream into each node without the stream ever re-sending the shape', () => {
        const state = fed(
            [
                attempt({ id: 'a-1', step_name: 'fetch', status: 'succeeded' }),
                attempt({ id: 'a-2', step_name: 'push', item: 'east', status: 'running' }),
            ],
            initialState(detail({ dag })),
        )
        const views = stepViews(state, NOW)

        expect(views[0]?.outcome).toBe('succeeded')
        expect(views[1]?.outcome).toBe('running')
        expect(views[1]?.strip.kind).toBe('chips')
    })

    test('says what a step is waiting on before it has been tried', () => {
        const views = stepViews(initialState(detail({ dag })), NOW)
        expect(views[0]?.detail).toBeNull()
        expect(views[1]?.detail).toBe('after fetch')
    })

    test("says the remote's own words while a step is parked on it", () => {
        const state = fed(
            [attempt({ id: 'a-1', status: 'waiting', waiting_message: 'the job is queued' })],
            initialState(detail({ dag })),
        )
        expect(stepViews(state, NOW)[0]?.detail).toBe('the job is queued')
    })

    test('says where an output went when it went to storage', () => {
        const state = fed(
            [attempt({ id: 'a-1', status: 'succeeded', output_uri: 'scratch://runs/r-1/body.json' })],
            initialState(detail({ dag })),
        )
        expect(stepViews(state, NOW)[0]?.detail).toBe('saves to scratch://runs/r-1/body.json')
    })

    test('says why a step failed, on the node itself', () => {
        const state = fed(
            [attempt({ id: 'a-1', status: 'failed', error: 'connection refused' })],
            initialState(detail({ dag })),
        )
        expect(stepViews(state, NOW)[0]?.detail).toBe('connection refused')
    })
})

describe('a whole connect, replayed', () => {
    const status: RunStatus = 'succeeded'

    test('lands in the same state whether it is read once or three times', () => {
        const frames = [
            { kind: 'attempt' as const, attempt: attempt({ id: 'a-1', status: 'succeeded' as AttemptStatus }) },
            { kind: 'log' as const, entry: entry({ id: 1 }) },
            { kind: 'attempt' as const, attempt: attempt({ id: 'a-2', step_name: 'push', status: 'running' }) },
            { kind: 'log' as const, entry: entry({ id: 2, step_name: 'push' }) },
            { kind: 'run' as const, run: run({ status, finished_at: '2026-03-01T12:00:00Z' }) },
        ]
        const once = frames.reduce(applyFrame, initialState(detail()))
        const thrice = [...frames, ...frames, ...frames].reduce(applyFrame, initialState(detail()))

        expect(thrice.run).toEqual(once.run)
        expect(thrice.attempts).toEqual(once.attempts)
        expect(thrice.logs).toEqual(once.logs)
        expect(thrice.order).toEqual(once.order)
        expect(resumeCursor(thrice)).toBe(resumeCursor(once))
    })
})


describe('how a run titles a step', () => {
    test('is the name the document gave it, with the key kept in mono beneath', () => {
        expect(headingOf(node({ code: 'quick', name: 'The quick one' }))).toEqual({
            title: 'The quick one',
            code: 'quick',
            named: true,
        })
    })

    test('is the key itself where the document named none, and the key is not drawn twice', () => {
        expect(headingOf(node({ code: 'quick', name: null }))).toEqual({ title: 'quick', code: null, named: false })
    })
})

describe('where a step\'s time went', () => {
    test('queued runs from a try becoming claimable to a worker taking it up', () => {
        const held = attempt({
            created_at: '2026-03-01T11:59:00Z',
            available_at: '2026-03-01T11:59:03Z',
            started_at: '2026-03-01T11:59:04Z',
        })
        expect(queuedOf([held])).toBe(1000)
    })

    test('a retry queues after the try it retries, so one element adds its tries up', () => {
        const tries = [
            attempt({ created_at: '2026-03-01T11:59:00Z', started_at: '2026-03-01T11:59:04Z' }),
            attempt({
                id: 'a-2',
                attempt: 2,
                created_at: '2026-03-01T11:59:05Z',
                started_at: '2026-03-01T11:59:07Z',
            }),
        ]
        expect(queuedOf(tries)).toBe(6000)
    })

    test('elements of a fan-out run beside each other, so the longest speaks for the step', () => {
        const tries = [
            attempt({ item: 'east', created_at: '2026-03-01T11:59:00Z', started_at: '2026-03-01T11:59:01Z' }),
            attempt({ id: 'a-2', item: 'west', created_at: '2026-03-01T11:59:00Z', started_at: '2026-03-01T11:59:05Z' }),
        ]
        expect(queuedOf(tries)).toBe(5000)
    })

    test('waiting is the parked time up to the probe that settled the try', () => {
        const parked = attempt({
            started_at: '2026-03-01T11:59:00Z',
            heartbeat_at: '2026-03-01T11:59:50Z',
            finished_at: '2026-03-01T11:59:51Z',
            poke_count: 5,
        })
        expect(waitingOf([parked], NOW)).toBe(50_000)
    })

    test('a try the deadline ended while parked counts the whole span as waiting', () => {
        const timedOut = attempt({
            status: 'skipped',
            started_at: '2026-03-01T11:59:00Z',
            heartbeat_at: '2026-03-01T11:59:48Z',
            finished_at: '2026-03-01T11:59:50Z',
            poke_count: 5,
        })
        expect(waitingOf([timedOut], NOW)).toBe(50_000)
    })

    test('a try still parked is measured against the clock the screen holds', () => {
        const parked = attempt({ started_at: '2026-03-01T11:59:10Z', poke_count: 2, status: 'waiting' })
        expect(waitingOf([parked], NOW)).toBe(50_000)
    })

    test('a step that never queued and never parked says nothing rather than zero', () => {
        const straight = attempt({
            created_at: '2026-03-01T11:59:00Z',
            started_at: '2026-03-01T11:59:00Z',
            finished_at: '2026-03-01T11:59:01Z',
        })
        expect(queuedOf([straight])).toBe(0)
        expect(waitingOf([straight], NOW)).toBeNull()
    })

    test('a span that reads as the whole step is not drawn beside it', () => {
        // A sensor that only waited waited for the whole of itself, and both facts on one screen
        // is the same fact twice; the record still carries all three.
        expect(readsAsTheWholeStep(10_116, 10_133)).toBe(true)
        expect(readsAsTheWholeStep(5943, 7300)).toBe(false)
        expect(readsAsTheWholeStep(null, 10_133)).toBe(false)
    })

    test('both are on every node the graph draws', () => {
        const state = fed([
            attempt({
                id: 'a-1',
                status: 'succeeded',
                created_at: '2026-03-01T11:59:00Z',
                started_at: '2026-03-01T11:59:02Z',
                heartbeat_at: '2026-03-01T11:59:12Z',
                finished_at: '2026-03-01T11:59:13Z',
                poke_count: 3,
            }),
        ])
        const view = stepViews(state, NOW)[0]
        expect(view?.queued_ms).toBe(2000)
        expect(view?.waiting_ms).toBe(10_000)
    })
})

describe('how long a step took', () => {
    test('runs from the first try starting to the last one finishing', () => {
        const tries = [
            attempt({ id: 'a-1', started_at: '2026-03-01T11:59:00Z', finished_at: '2026-03-01T11:59:02Z' }),
            attempt({ id: 'a-2', attempt: 2, started_at: '2026-03-01T11:59:20Z', finished_at: '2026-03-01T11:59:30Z' }),
        ]
        expect(durationOf(tries, 'succeeded', NOW)).toBe(30_000)
    })

    test('is the earliest start and the latest finish, not the first and last to arrive', () => {
        // A fan-out's elements settle in whatever order the workers free up, so arrival order is
        // not clock order. This is the span the run report measures, and the two say one number.
        const tries = [
            attempt({ id: 'a-1', started_at: '2026-03-01T11:59:00.100Z', finished_at: '2026-03-01T11:59:00.450Z' }),
            attempt({ id: 'a-2', started_at: '2026-03-01T11:59:00.050Z', finished_at: '2026-03-01T11:59:00.421Z' }),
        ]
        expect(durationOf(tries, 'succeeded', NOW)).toBe(400)
        expect(durationOf(tries.toReversed(), 'succeeded', NOW)).toBe(400)
    })

    test('counts a running step against the clock the screen already holds', () => {
        expect(durationOf([attempt({ started_at: '2026-03-01T11:59:10Z' })], 'running', NOW)).toBe(50_000)
    })

    test('says nothing about a step that has not started', () => {
        expect(durationOf([], 'pending', NOW)).toBeNull()
        expect(durationOf([attempt({ started_at: null })], 'skipped', NOW)).toBeNull()
    })

    test('says nothing about a settled step whose tries never finished', () => {
        expect(durationOf([attempt({ status: 'cancelled', finished_at: null })], 'cancelled', NOW)).toBeNull()
    })

    test('is on every node the graph draws', () => {
        const state = fed([
            attempt({ id: 'a-1', status: 'succeeded', started_at: '2026-03-01T11:59:00Z', finished_at: '2026-03-01T11:59:01Z' }),
        ])
        expect(stepViews(state, NOW)[0]?.duration_ms).toBe(1000)
    })
})

describe('the state a node is drawn in', () => {
    test('is the outcome itself for a step that does not fan out', () => {
        expect(nodeTone(drawn({ outcome: 'failed' }))).toBe('failed')
        expect(nodeTone(drawn({ outcome: 'running' }))).toBe('running')
    })

    test('is completed with errors where items: continue absorbed the failures', () => {
        const tolerated = drawn({
            node: node({ fan_out: true, outcome: 'succeeded', items_total: 3, items_failed: 1 }),
            outcome: 'failed',
        })
        expect(toleratedFanOut(tolerated)).toBe(true)
        expect(nodeTone(tolerated)).toBe('completed_with_errors')
    })

    test('stays failed for a fan-out the engine itself failed, whatever the policy was', () => {
        const failed = drawn({
            node: node({ fan_out: true, outcome: 'failed', items_total: 3, items_failed: 3 }),
            outcome: 'failed',
        })
        expect(toleratedFanOut(failed)).toBe(false)
        expect(nodeTone(failed)).toBe('failed')
    })

    test('is not tolerated where no element failed at all', () => {
        expect(toleratedFanOut(drawn({ node: node({ fan_out: true, outcome: 'succeeded', items_total: 3 }) }))).toBe(
            false,
        )
    })

    test('leaves a fan-out that is still going in its live state', () => {
        const live = drawn({
            node: node({ fan_out: true, outcome: 'succeeded', items_total: 3, items_failed: 1 }),
            outcome: 'running',
        })
        expect(nodeTone(live)).toBe('running')
    })
})

describe('what an edge is drawn as', () => {
    test('takes a tint from the state its source settled in', () => {
        expect(edgeTone(drawn({ outcome: 'succeeded' }), drawn())).toBe('dg-edge-good')
        expect(edgeTone(drawn({ outcome: 'failed' }), drawn())).toBe('dg-edge-critical')
    })

    test('agrees with the box it leaves, so a tolerated fan-out tints its edges amber', () => {
        const tolerated = drawn({
            node: node({ fan_out: true, outcome: 'succeeded', items_total: 3, items_failed: 1 }),
            outcome: 'failed',
        })
        expect(edgeTone(tolerated, drawn())).toBe('dg-edge-warning')
    })

    test('is dashed into a step that did not happen, on top of whatever tint it carries', () => {
        expect(edgeTone(drawn({ outcome: 'succeeded' }), drawn({ outcome: 'skipped' }))).toBe(
            'dg-edge-good dg-edge-skipped',
        )
        expect(edgeTone(drawn({ outcome: 'pending' }), drawn({ outcome: 'skipped' }))).toBe('dg-edge-skipped')
    })

    test('is plain for a step nothing has happened to, and for an end the graph does not carry', () => {
        expect(edgeTone(drawn({ outcome: 'running' }), drawn({ outcome: 'pending' }))).toBe('')
        expect(edgeTone(undefined, undefined)).toBe('')
    })
})

describe('what an edge is carrying while a run is live', () => {
    /** A step by the name its edges are keyed on. */
    function step(code: string, over: Partial<StepView> = {}): StepView {
        return drawn({ node: node({ code }), ...over })
    }

    const moving = { handing: new Set<string>(), reduced: false }

    test('moves out of a step that has produced into one still reading it', () => {
        const motion = edgeMotion(step('parse', { outcome: 'succeeded' }), step('report', { outcome: 'running' }), moving)
        expect(motion).toBe('flowing')
        expect(edgeClasses(step('parse', { outcome: 'succeeded' }), step('report', { outcome: 'running' }), moving)).toBe(
            'dg-edge-good dg-edge-flowing',
        )
    })

    test('moves out of a fan-out whose failures were tolerated, which produced a short batch', () => {
        const tolerated = step('per_region', {
            node: node({ name: 'per_region', fan_out: true, outcome: 'succeeded', items_total: 3, items_failed: 1 }),
            outcome: 'failed',
        })
        expect(edgeMotion(tolerated, step('report', { outcome: 'running' }), moving)).toBe('flowing')
    })

    test('is still out of a step that failed, was skipped, or has not produced anything yet', () => {
        expect(edgeMotion(step('parse', { outcome: 'failed' }), step('report', { outcome: 'running' }), moving)).toBe('still')
        expect(edgeMotion(step('parse', { outcome: 'skipped' }), step('report', { outcome: 'running' }), moving)).toBe('still')
        expect(edgeMotion(step('parse', { outcome: 'running' }), step('report', { outcome: 'pending' }), moving)).toBe('still')
    })

    test('is still where both ends have settled, which is every edge of a terminal run', () => {
        expect(edgeMotion(step('parse', { outcome: 'succeeded' }), step('report', { outcome: 'succeeded' }), moving)).toBe(
            'still',
        )
        expect(edgeMotion(undefined, undefined, moving)).toBe('still')
    })

    test('plays one handover into a step that can still read what just landed', () => {
        const handing = { handing: new Set(['parse']), reduced: false }
        expect(edgeMotion(step('parse', { outcome: 'succeeded' }), step('report', { outcome: 'pending' }), handing)).toBe(
            'handover',
        )
        // A handover comes first where a dependent is already running: one moment, then the flow.
        expect(edgeMotion(step('parse', { outcome: 'succeeded' }), step('report', { outcome: 'running' }), handing)).toBe(
            'handover',
        )
        // Into a step that will never read it there is nothing to hand over.
        expect(edgeMotion(step('parse', { outcome: 'succeeded' }), step('report', { outcome: 'skipped' }), handing)).toBe(
            'still',
        )
    })

    test('lights rather than moves for somebody who asked for less motion', () => {
        const reduced = { handing: new Set(['parse']), reduced: true }
        expect(edgeMotion(step('parse', { outcome: 'succeeded' }), step('report', { outcome: 'running' }), reduced)).toBe(
            'lit',
        )
        expect(edgeMotion(step('parse', { outcome: 'succeeded' }), step('report', { outcome: 'pending' }), reduced)).toBe(
            'still',
        )
        expect(edgeClasses(step('parse', { outcome: 'succeeded' }), step('report', { outcome: 'running' }), reduced)).toBe(
            'dg-edge-good dg-edge-lit',
        )
    })
})

describe('when a step hands its output on', () => {
    function step(code: string, outcome: StepView['outcome']): StepView {
        return drawn({ node: node({ code }), outcome })
    }

    test('is the render that moved it there, and no other', () => {
        const before = drawnStates([step('parse', 'running'), step('report', 'pending')])
        expect(handovers(before, [step('parse', 'succeeded'), step('report', 'pending')])).toEqual(['parse'])
        expect(handovers(before, [step('parse', 'running'), step('report', 'pending')])).toEqual([])
    })

    test('is nothing at all for a run that had already settled when it was opened', () => {
        expect(handovers(new Map(), [step('parse', 'succeeded'), step('report', 'succeeded')])).toEqual([])
    })

    test('is not repeated for a step that was already succeeded', () => {
        const before = drawnStates([step('parse', 'succeeded')])
        expect(handovers(before, [step('parse', 'succeeded')])).toEqual([])
    })
})

describe('the order a step lists its tries in', () => {
    /** One element of a fan-out, named and placed the way the wire places it. */
    function element(key: string, index: number, over: Partial<AttemptEvent> = {}): AttemptEvent {
        return attempt({ id: `a-${key}`, run_item_id: `item-${key}`, item: key, item_index: index, ...over })
    }

    test('reads the elements in fan-out order however late each of them finished', () => {
        // The stream reports an element when it moves, so the arrival order is the order they
        // settled in; the document wrote them north first and that is the order to read them in.
        const arrived = [element('central', 4), element('west', 3), element('east', 2), element('north', 0)]
        expect(attemptOrder(arrived).map((one) => one.item)).toEqual(['north', 'east', 'west', 'central'])
    })

    test('keeps one element together, newest try first', () => {
        const first = element('north', 0, { id: 'a-north-1', attempt: 1 })
        const retry = element('north', 0, { id: 'a-north-2', attempt: 2 })
        const other = element('south', 1)
        expect(attemptOrder([first, other, retry]).map((one) => one.id)).toEqual([
            'a-north-2',
            'a-north-1',
            'a-south',
        ])
    })

    test('leaves a step that fans out to nothing with its newest try first', () => {
        const first = attempt({ id: 'a-1', attempt: 1 })
        const second = attempt({ id: 'a-2', attempt: 2 })
        expect(attemptOrder([first, second]).map((one) => one.id)).toEqual(['a-2', 'a-1'])
    })
})

describe("what a fan-out step produced", () => {
    function element(key: string, index: number, over: Partial<AttemptEvent> = {}): AttemptEvent {
        return attempt({ id: `a-${key}`, run_item_id: `item-${key}`, item: key, item_index: index, ...over })
    }

    test("is one output per element, keyed by the element's label and in item order", () => {
        const north = element('north', 0, { status: 'succeeded', output: { rows: 3 } })
        const south = element('south', 1, { status: 'succeeded', output: { rows: 5 } })
        expect(itemOutputs([south, north]).map((one) => [one.key, one.produced?.output])).toEqual([
            ['north', { rows: 3 }],
            ['south', { rows: 5 }],
        ])
    })

    test('says a failed element produced nothing rather than producing null', () => {
        // The engine leaves a failed element out of the list the next step reads; a null in its
        // place would be a value that step would try to read.
        const failed = element('east', 2, { status: 'failed', error: 'no answer' })
        expect(itemOutputs([failed])).toEqual([
            { id: 'item-east', key: 'east', status: 'failed', produced: null },
        ])
    })

    test("takes the newest try that produced anything, not the newest try", () => {
        const produced = element('north', 0, { id: 'a-north-1', attempt: 1, output: { rows: 3 } })
        const retry = element('north', 0, { id: 'a-north-2', attempt: 2, status: 'running' })
        expect(itemOutputs([produced, retry])[0]?.produced?.id).toBe('a-north-1')
    })
})

describe('which element a log line was written for', () => {
    test('joins the line to the attempt that wrote it, which is what carries the label', () => {
        const state = fed([
            attempt({ id: 'a-north', run_item_id: 'item-north', item: 'north', item_index: 0 }),
            attempt({ id: 'a-south', run_item_id: 'item-south', item: 'south', item_index: 1 }),
        ])
        const labels = itemLabels(state)
        expect(itemOfEntry(labels, 'a-south')).toBe('south')
    })

    test('leaves a line of a step that fans out to nothing unlabelled', () => {
        const labels = itemLabels(fed([attempt({ id: 'a-1' })]))
        expect(itemOfEntry(labels, 'a-1')).toBeNull()
        expect(itemOfEntry(labels, null)).toBeNull()
    })
})

describe("an attempt's output, read", () => {
    test('is the value alone when the block wrapped it in the envelope', () => {
        const wrapped = attempt({ output: { value: { rows: 3 }, output_uri: null, output_bytes: null } })
        expect(outputReading(wrapped)).toEqual({ value: { rows: 3 }, uri: null, bytes: null })
    })

    test('is where it went when the block wrote it to storage instead', () => {
        const saved = attempt({ output: { value: null, output_uri: 's3://bucket/out.json', output_bytes: 4096 } })
        expect(outputReading(saved)).toEqual({ value: null, uri: 's3://bucket/out.json', bytes: 4096 })
    })

    test('is where it went when the engine spilled it, whatever the output says', () => {
        const spilled = attempt({
            output: { value: { rows: 3 }, output_uri: null, output_bytes: null },
            output_uri: 'file:///runs/out.json',
            output_bytes: 512,
        })
        expect(outputReading(spilled)).toEqual({ value: null, uri: 'file:///runs/out.json', bytes: 512 })
    })

    test('leaves an output that is not the envelope exactly as the block wrote it', () => {
        const plain = attempt({ output: { status_code: 200, body: 'ok' } })
        expect(outputReading(plain)).toEqual({ value: { status_code: 200, body: 'ok' }, uri: null, bytes: null })
    })
})
