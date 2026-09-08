import { describe, expect, test } from 'vitest'

import { DEFAULT_EVENT, frameParser, readFrames, type SseFrame } from '@/lib/sse'

/** Feed a whole text through one parser, as if it arrived in one chunk. */
function frames(text: string): SseFrame[] {
    const parser = frameParser()
    const seen: SseFrame[] = []
    for (const line of text.split('\n')) seen.push(...parser.parseLine(line))
    return seen
}

/** A byte stream that hands back exactly the chunks given, in order. */
function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder()
    return new ReadableStream<Uint8Array>({
        start(controller) {
            for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
            controller.close()
        },
    })
}

async function collect(chunks: string[]): Promise<SseFrame[]> {
    const seen: SseFrame[] = []
    for await (const frame of readFrames(streamOf(chunks), frameParser())) seen.push(frame)
    return seen
}

describe('the frame parser', () => {
    test('reads the event name, the data, and the id the stream stated', () => {
        expect(frames('id: 42\nevent: log\ndata: {"message":"hello"}\n\n')).toEqual([
            { event: 'log', data: '{"message":"hello"}', id: '42' },
        ])
    })

    test('names an unnamed frame the way the SSE default names it', () => {
        expect(frames('data: bare\n\n')).toEqual([{ event: DEFAULT_EVENT, data: 'bare', id: null }])
    })

    test('joins several data lines of one frame with newlines', () => {
        expect(frames('event: log\ndata: first\ndata: second\n\n')[0].data).toBe('first\nsecond')
    })

    test('carries the last stated id onto later frames, which is what a reconnect resumes past', () => {
        const seen = frames('id: 7\nevent: log\ndata: a\n\nevent: attempt\ndata: b\n\n')
        expect(seen.map((frame) => frame.id)).toEqual(['7', '7'])
    })

    test('reports the last stated id, so a caller can resume without reading the frames', () => {
        const parser = frameParser()
        const seen: SseFrame[] = []
        for (const line of 'id: 91\ndata: x\n\n'.split('\n')) seen.push(...parser.parseLine(line))
        expect(parser.lastEventId()).toBe('91')
    })

    test('strips exactly one space after the colon, and keeps a second one', () => {
        expect(frames('data:  padded\n\n')[0].data).toBe(' padded')
        expect(frames('data:tight\n\n')[0].data).toBe('tight')
    })

    test('dispatches nothing for a comment, which is how a server keeps an idle stream open', () => {
        expect(frames(': ping\n\n')).toEqual([])
    })

    test('dispatches nothing for a frame that carried no data', () => {
        expect(frames('event: log\n\n')).toEqual([])
    })

    test('does not leak an event name from a frame that dispatched nothing into the next one', () => {
        expect(frames('event: log\n\ndata: plain\n\n')[0].event).toBe(DEFAULT_EVENT)
    })
})

describe('reading a byte stream', () => {
    test('joins a frame split across chunk boundaries', async () => {
        expect(await collect(['event: att', 'empt\ndata: {"st', 'atus":"running"}\n\n'])).toEqual([
            { event: 'attempt', data: '{"status":"running"}', id: null },
        ])
    })

    test('reads CRLF line endings, which the SSE grammar allows and this parser must not split on', async () => {
        expect(await collect(['id: 3\r\nevent: log\r\ndata: crlf\r\n\r\n'])).toEqual([
            { event: 'log', data: 'crlf', id: '3' },
        ])
    })

    test('a chunk ending between the two halves of a CRLF pair does not invent a blank line', async () => {
        expect(await collect(['event: log\r\ndata: split\r', '\n\r\n'])).toEqual([
            { event: 'log', data: 'split', id: null },
        ])
    })

    test('a terminal frame arriving without its blank line is still delivered', async () => {
        expect(await collect(['event: end\ndata: {}'])).toEqual([{ event: 'end', data: '{}', id: null }])
    })

    test('delivers several frames from one chunk, in order', async () => {
        const seen = await collect(['event: attempt\ndata: a\n\nevent: log\ndata: b\n\nevent: end\ndata: {}\n\n'])
        expect(seen.map((frame) => frame.event)).toEqual(['attempt', 'log', 'end'])
    })

    test('reassembles a multibyte character split across chunks', async () => {
        const encoder = new TextEncoder()
        const bytes = encoder.encode('data: å\n\n')
        const stream = new ReadableStream<Uint8Array>({
            start(controller) {
                controller.enqueue(bytes.slice(0, 7))
                controller.enqueue(bytes.slice(7))
                controller.close()
            },
        })
        const seen: SseFrame[] = []
        for await (const frame of readFrames(stream, frameParser())) seen.push(frame)
        expect(seen[0].data).toBe('å')
    })
})
