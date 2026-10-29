/**
 * The source resources, as this bundle reads them.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface here mirrors a pydantic model in
 * `dirigent_client.schemas.sources` member for member.
 *
 * UNLIKE A TRIGGER, A SOURCE HAS AN INSTANCE-WIDE LISTING. `/sources` pages every source on
 * the instance, so the screen reads it on its own cursor rather than walking pipelines.
 */

import { apiJson, type JsonMap, type Page } from '@/lib/api'
import { LABELS } from '@/lib/labels'
import { PAGE } from '@/lib/paging'
import type { OutcomeTone, WebhookTokenOut } from '@/lib/triggers'

/** Whether a source takes inputs now. `SourceState`. */
export type SourceState = 'listening' | 'backlogged' | 'draining' | 'paused'

/** What came of one input that reached a source. `InputOutcome`. */
export type InputOutcome = 'accepted' | 'replied' | 'refused' | 'timed_out'

/** A source as a listing shows it, never its token. `SourceOut`. */
export interface SourceOut {
    id: string
    /** The code of the pipeline the source belongs to. */
    pipeline: string
    /** The source's step key. */
    code: string
    name: string | null
    description: string | null
    kind: string
    state: SourceState
    /** The methods a received source answers; empty for a kind the server does not receive. */
    methods: string[]
    route: string | null
    /** Where a received source is called: the endpoint prefix and the template. */
    url_path: string | null
    auth: string | null
    token_prefix: string | null
    in_flight: number
    max_in_flight: number | null
    accepted: number
    refused: number
    last_input_at: string | null
    created_at: string
}

/** One input that reached a source, and the run or the refusal it became. `SourceInputOut`. */
export interface SourceInputOut {
    id: number
    created_at: string
    outcome: InputOutcome
    /** The HTTP status the caller was answered with. */
    status: number
    run_id: string | null
    code: string | null
    reason: string | null
    params: JsonMap | null
    method: string
    path: string
    body_bytes: number
    duration_ms: number
    caller: string | null
}

/** A token freshly minted for a source, answered once. `SourceTokenOut`. */
export interface SourceTokenOut {
    source_id: string
    pipeline: string
    code: string
    token: string
    prefix: string
    url_path: string
}

/** The one key a source is told apart by on this instance. */
export function sourceId(source: Pick<SourceOut, 'pipeline' | 'code'>): string {
    return `${source.pipeline}/${source.code}`
}

/** The key one input is told apart by in its journal. */
export function inputId(input: SourceInputOut): string {
    return String(input.id)
}

/** Read one page of every source on the instance. */
export function readSourcePage(after: string | null): Promise<Page<SourceOut>> {
    return apiJson<Page<SourceOut>>(`/sources${cursor(after)}`)
}

/** Read one page of a source's journal, newest first. */
export function readSourceInputs(
    pipeline: string,
    code: string,
    after: string | null,
): Promise<Page<SourceInputOut>> {
    return apiJson<Page<SourceInputOut>>(`${sourcePath(pipeline, code)}/inputs${cursor(after)}`)
}

/** Stop a source taking inputs, or start it again, keeping its token and its journal. */
export function setSourcePaused(pipeline: string, code: string, paused: boolean): Promise<SourceOut> {
    return apiJson<SourceOut>(`${sourcePath(pipeline, code)}/${paused ? '$pause' : '$resume'}`, {
        method: 'POST',
    })
}

/** Mint a new token for a source, forgetting the old one at once. */
export function rotateSourceToken(pipeline: string, code: string): Promise<SourceTokenOut> {
    return apiJson<SourceTokenOut>(`${sourcePath(pipeline, code)}/$rotate-token`, { method: 'POST' })
}

/** The token as the dialog that shows a token once reads it. */
export function shownToken(token: SourceTokenOut): WebhookTokenOut {
    return {
        webhook_id: token.source_id,
        code: token.code,
        token: token.token,
        prefix: token.prefix,
        url_path: token.url_path,
    }
}

function sourcePath(pipeline: string, code: string): string {
    return `/pipelines/${encodeURIComponent(pipeline)}/sources/${encodeURIComponent(code)}`
}

function cursor(after: string | null): string {
    const query = new URLSearchParams({ limit: String(PAGE) })
    if (after !== null) query.set('after', after)
    return `?${query.toString()}`
}

/** Whether a source is paused, by its own verb or its pipeline's. */
export function isPaused(source: Pick<SourceOut, 'state'>): boolean {
    return source.state === 'paused' || source.state === 'draining'
}

/** How a source's state is drawn: the word, and the tone of its dot. */
export function stateView(source: Pick<SourceOut, 'state'>): {
    label: string
    tone: OutcomeTone
} {
    return {
        label: LABELS.state.source[source.state],
        tone: STATE_TONES[source.state],
    }
}

const STATE_TONES: Record<SourceState, OutcomeTone> = {
    listening: 'good',
    backlogged: 'warn',
    draining: 'warn',
    paused: 'quiet',
}

/** Where a received source is called, as one line: its methods and its path. */
export function routeLine(source: Pick<SourceOut, 'methods' | 'url_path'>): string | null {
    if (source.url_path === null || source.methods.length === 0) return null
    return `${source.methods.join(', ')} ${source.url_path}`
}

/** How a caller authenticates, in the words the panel uses, or null for a kind with no caller. */
export function authLine(source: Pick<SourceOut, 'auth' | 'token_prefix'>): string | null {
    if (source.auth === 'public') return LABELS.triggers.source.public
    if (source.auth === 'token' && source.token_prefix !== null)
        return LABELS.triggers.source.token(source.token_prefix)
    return null
}

/** What one input amounted to: the word, the tone, and the run it started. */
export function inputView(input: SourceInputOut): {
    label: string
    tone: OutcomeTone
    runId: string | null
} {
    const failed = input.status >= 400
    const tone: OutcomeTone =
        input.outcome === 'refused' || input.outcome === 'timed_out' ? 'critical' : failed ? 'warn' : 'good'
    return {
        label: LABELS.triggers.source.outcome[input.outcome],
        tone,
        runId: input.run_id,
    }
}
