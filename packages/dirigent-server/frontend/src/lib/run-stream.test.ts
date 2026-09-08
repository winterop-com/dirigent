import { describe, expect, test } from 'vitest'

import {
    BACKOFF_CEILING_MS,
    BACKOFF_FLOOR_MS,
    backoffFor,
    CONTINUE_DELAY_MS,
    follow,
    type StreamSource,
} from '@/lib/run-stream'
import { decodeFrame, reduce, type RunDetailState, type StreamState } from '@/lib/run-detail'
import type { DagNode, LogEntryOut, RunDetailOut } from '@/lib/runs'
import type { SseFrame } from '@/lib/sse'

/** No step here fans out, so no line carries an item label. */
const NO_ITEMS = new Map<string, string>()
import { EVERY_LINE, stepChoices, stepOf, visibleLines } from '@/lib/terminal'

/** One frame, spelled the way `lib/sse` hands one over. */
function frame(event: string, data = '{}', id: string | null = null): SseFrame {
    return { event, data, id }
}

/** What one connection was asked for, and what it did. */
interface Opened {
    after: string | null
}

/**
 * A stand-in for `streamSse` that counts how many connections are open at once.
 *
 * THIS COUNTER IS THE ONE-STREAM RULE. `GET /runs/{id}/$events` is multiplexed and a screen is
 * allowed exactly one of them; the server caps a principal at eight streams, and a second one
 * per pane would spend that budget on delivering the same story twice. `concurrent` is asserted
 * on in every test below, so opening a second connection anywhere in `follow` fails this file.
 */
function recorder(scripts: (SseFrame[] | Error)[]) {
    const opens: Opened[] = []
    let live = 0
    let concurrent = 0
    let index = 0

    const open: StreamSource = (_path, options) => {
        opens.push({ after: options.after ?? null })
        const script = scripts[Math.min(index, scripts.length - 1)]
        index += 1
        live += 1
        concurrent = Math.max(concurrent, live)
        return {
            async *[Symbol.asyncIterator]() {
                try {
                    if (script instanceof Error) throw script
                    // A scripted stream delivers in order, which is what a stream is.
                    // oxlint-disable-next-line no-await-in-loop
                    for (const one of script) yield await Promise.resolve(one)
                } finally {
                    live -= 1
                }
            },
        }
    }

    return {
        open,
        opens,
        count: () => opens.length,
        concurrent: () => concurrent,
    }
}

/** Follow a run with a scripted connection, collecting what the caller was told. */
async function drive(
    scripts: (SseFrame[] | Error)[],
    options: { settledAfter?: number; stopAfter?: number } = {},
) {
    const source = recorder(scripts)
    const frames: SseFrame[] = []
    const states: StreamState[] = []
    const waits: number[] = []
    const controller = new AbortController()
    let ends = 0

    await follow('r-1', {
        open: source.open,
        signal: controller.signal,
        cursor: () => (frames.length === 0 ? null : (frames.findLast((one) => one.id !== null)?.id ?? null)),
        settled: () => {
            ends += 1
            return ends >= (options.settledAfter ?? 1)
        },
        onFrame: (one) => {
            frames.push(one)
        },
        onState: (state) => {
            states.push(state)
        },
        wait: (ms) => {
            waits.push(ms)
            if (options.stopAfter !== undefined && waits.length >= options.stopAfter) controller.abort()
            return Promise.resolve()
        },
    })

    return { frames, states, waits, source }
}

describe('the reconnect wait', () => {
    test('is nothing before anything has failed', () => {
        expect(backoffFor(0)).toBe(0)
    })

    test('starts at the floor and doubles', () => {
        expect(backoffFor(1)).toBe(BACKOFF_FLOOR_MS)
        expect(backoffFor(2)).toBe(BACKOFF_FLOOR_MS * 2)
        expect(backoffFor(3)).toBe(BACKOFF_FLOOR_MS * 4)
    })

    test('stops at the ceiling, so a server that is down is not hammered', () => {
        expect(backoffFor(20)).toBe(BACKOFF_CEILING_MS)
    })
})

describe('following one run', () => {
    test('opens exactly one stream and stops when the run has settled', async () => {
        const { frames, states, source } = await drive([[frame('attempt'), frame('run'), frame('end')]])

        expect(source.count()).toBe(1)
        expect(source.concurrent()).toBe(1)
        expect(frames.map((one) => one.event)).toEqual(['attempt', 'run', 'end'])
        expect(states.at(-1)).toBe('ended')
    })

    test('never holds two connections open, however many times it reconnects', async () => {
        const { source } = await drive([new Error('dropped'), new Error('dropped again'), [frame('end')]])
        expect(source.concurrent()).toBe(1)
        expect(source.count()).toBe(3)
    })

    test('says where the connection is, so the status bar can state it', async () => {
        const { states } = await drive([new Error('dropped'), [frame('log', '{}', '4'), frame('end')]])
        expect(states).toEqual(['connecting', 'reconnecting', 'live', 'live', 'ended'])
    })

    test('resumes past the last id the stream stated rather than replaying it', async () => {
        const { source } = await drive([[frame('log', '{}', '11')], [frame('end')]])

        expect(source.opens[0]?.after).toBeNull()
        expect(source.opens[1]?.after).toBe('11')
    })

    test('widens the wait between failed connections', async () => {
        const { waits } = await drive([new Error('one'), new Error('two'), [frame('end')]])
        expect(waits).toEqual([BACKOFF_FLOOR_MS, BACKOFF_FLOOR_MS * 2])
    })

    test('reopens when the server closed a tail at its own limit and the run is still going', async () => {
        // The server ends a stream after its wall-clock hour whether the run settled or not.
        // Which it was is a question about the run, so the caller answers it.
        const { source, waits } = await drive([[frame('end')], [frame('end')]], { settledAfter: 2 })

        expect(source.count()).toBe(2)
        expect(source.concurrent()).toBe(1)
        expect(waits).toHaveLength(1)
    })

    test('reopens on an expired frame without showing it to the screen', async () => {
        const { frames, source, waits } = await drive([
            [frame('log', '{}', '7'), frame('expired')],
            [frame('run'), frame('end')],
        ])

        expect(frames.map((one) => one.event)).toEqual(['log', 'run', 'end'])
        expect(source.count()).toBe(2)
        expect(source.concurrent()).toBe(1)
        expect(source.opens[1]?.after).toBe('7')
        expect(waits).toEqual([CONTINUE_DELAY_MS])
    })

    test('stops the moment it is aborted, leaving nothing open', async () => {
        const { source } = await drive([new Error('dropped')], { stopAfter: 1 })
        expect(source.concurrent()).toBe(1)
        expect(source.count()).toBe(1)
    })

    test('opens nothing at all when the signal is aborted before it starts', async () => {
        const source = recorder([[frame('end')]])
        const controller = new AbortController()
        controller.abort()

        await follow('r-1', {
            open: source.open,
            signal: controller.signal,
            cursor: () => null,
            settled: () => true,
            onFrame: () => undefined,
            onState: () => undefined,
            wait: () => Promise.resolve(),
        })

        expect(source.count()).toBe(0)
    })
})

/** One log entry as the stream carries one. */
function logEntry(id: number, step: string | null, level: LogEntryOut['level'], message: string): LogEntryOut {
    return {
        id,
        run_id: 'r-1',
        step_name: step,
        step_attempt_id: null,
        level,
        message,
        fields: null,
        created_at: '2026-03-01T11:59:11Z',
    }
}

/** The run this screen read before it opened anything: two steps, and no lines yet. */
function opened(): RunDetailOut {
    return {
        run: {
            id: 'r-1',
            pipeline: 'nightly',
            pipeline_version: 1,
            priority: 'normal',
            status: 'running',
            params: {},
            triggered_by_kind: 'user',
            triggered_by_label: 'dev',
            trace_id: null,
            error: null,
            failed_step: null,
            started_at: null,
            finished_at: null,
            window_start: null,
            window_end: null,
            created_at: '2026-03-01T11:58:00Z',
        },
        dag: {
            nodes: ['fetch', 'shape'].map((code) => ({
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
            })),
            edges: [],
        },
        items_total: 0,
        attempts_total: 0,
        waiting_for_workers: null,
    }
}

describe('the terminal drawer costs no connection', () => {
    /**
     * THE DRAWER IS A READING OF THE ONE STREAM, NOT A SECOND ONE.
     *
     * A console across the foot of the run screen is exactly the shape of thing that arrives
     * with a log tail of its own attached -- `runs/{id}/$logs?follow=sse` is right there and the
     * server would answer it. It would also spend one of this principal's eight streams
     * delivering lines the screen already has, with no ordering between the copies. So the
     * drawer is fed from the same reducer state as the graph and the panel: this drives `follow`
     * exactly as the screen does, then reads the whole of the drawer's data path off the result,
     * and the counter above must still say one.
     */
    test('draws every line of a run without opening a stream of its own', async () => {
        const source = recorder([
            [
                frame('log', JSON.stringify(logEntry(1, 'fetch', 'info', 'reaching out')), '1'),
                frame('log', JSON.stringify(logEntry(2, 'shape', 'warning', 'retrying once')), '2'),
                frame('log', JSON.stringify(logEntry(3, 'fetch', 'error', 'it gave up')), '3'),
                frame('end'),
            ],
        ])
        const controller = new AbortController()
        let held: RunDetailState | null = reduce(null, { kind: 'loaded', detail: opened() })

        await follow('r-1', {
            open: source.open,
            signal: controller.signal,
            cursor: () => null,
            settled: () => true,
            onFrame: (one) => {
                held = reduce(held, { kind: 'frame', frame: decodeFrame(one) })
            },
            onState: (where) => {
                held = reduce(held, { kind: 'stream', stream: where })
            },
            wait: () => Promise.resolve(),
        })

        const state: RunDetailState | null = held
        expect(state).not.toBeNull()
        if (state === null) return

        // The whole of what the drawer reads: the lines, each filter over them, the step select,
        // and the step a prefix opens. None of it reaches the network.
        expect(visibleLines(state.logs, EVERY_LINE, NO_ITEMS).map((line) => line.id)).toEqual([1, 2, 3])
        expect(visibleLines(state.logs, { ...EVERY_LINE, step: 'fetch' }, NO_ITEMS).map((line) => line.id)).toEqual([1, 3])
        expect(visibleLines(state.logs, { ...EVERY_LINE, level: 'error' }, NO_ITEMS).map((line) => line.id)).toEqual([3])
        expect(stepChoices(state)).toEqual(['fetch', 'shape'])
        expect(stepOf(visibleLines(state.logs, EVERY_LINE, NO_ITEMS)[0] as LogEntryOut)).toBe('fetch')

        expect(source.count()).toBe(1)
        expect(source.concurrent()).toBe(1)
    })
})

/** One node of a graph, as the read hands one over. */
function dagNode(code: string, dependsOn: string[] = []): DagNode {
    return {
        code,
        name: null,
        block: 'time.sleep',
        outcome: 'pending',
        depends_on: dependsOn,
        rule: 'all_success',
        fan_out: false,
        items_total: 0,
        items_failed: 0,
        attempts: 0,
    }
}

/** A run of three waits that one step joins: the shape whose edges are the whole point. */
function raced(): RunDetailOut {
    return {
        ...opened(),
        dag: {
            nodes: [dagNode('slow'), dagNode('middling'), dagNode('quick'), dagNode('report', ['slow', 'middling', 'quick'])],
            edges: [
                ['slow', 'report'],
                ['middling', 'report'],
                ['quick', 'report'],
            ],
        },
    }
}

describe('the graph a run was read with', () => {
    /**
     * THE READ IS THE GRAPH AND THE STREAM IS EVERYTHING AFTER. A step's state, its lines and
     * the run's ending all arrive on the stream; the shape does not, and nothing the stream
     * says may quietly re-order the nodes or drop an edge from under the canvas.
     */
    test('is the graph the stream leaves behind, node for node and edge for edge', async () => {
        const read = raced()
        const source = recorder([
            [
                frame('attempt', JSON.stringify({ id: 'a-1', step_name: 'quick', attempt: 1, status: 'running' })),
                frame('log', JSON.stringify(logEntry(1, 'quick', 'info', 'waiting')), '1'),
                frame('attempt', JSON.stringify({ id: 'a-1', step_name: 'quick', attempt: 1, status: 'succeeded' })),
                frame('run', JSON.stringify({ ...read.run, status: 'succeeded' })),
                frame('end'),
            ],
        ])
        const controller = new AbortController()
        let held: RunDetailState | null = reduce(null, { kind: 'loaded', detail: read })

        await follow('r-1', {
            open: source.open,
            signal: controller.signal,
            cursor: () => null,
            settled: () => true,
            onFrame: (one) => {
                held = reduce(held, { kind: 'frame', frame: decodeFrame(one) })
            },
            onState: (where) => {
                held = reduce(held, { kind: 'stream', stream: where })
            },
            wait: () => Promise.resolve(),
        })

        const state: RunDetailState | null = held
        expect(state).not.toBeNull()
        if (state === null) return

        expect(state.dag.edges).toEqual(read.dag.edges)
        expect(state.dag.nodes.map((one) => one.code)).toEqual(['slow', 'middling', 'quick', 'report'])
        // The very object, which is what keeps the canvas from being placed a second time.
        expect(state.dag).toBe(read.dag)
        expect(state.run.status).toBe('succeeded')
    })
})
