/**
 * Each fan-out element's record over a window: what `GET /pipelines/{code}/items/$stats` answers.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface mirrors a pydantic model in
 * `dirigent_client.schemas.runs` member for member.
 */

import { apiJson } from '@/lib/api'
import type { ItemStatus } from '@/lib/status'

/** How one element went on one UTC day. `ItemDay`. */
export interface ItemDay {
    /** `YYYY-MM-DD`. */
    day: string
    succeeded: number
    failed: number
    skipped: number
}

/** How one element of one step went over the window. `ItemHealth`. */
export interface ItemHealth {
    step: string
    /** The element's key, which is what the run grid names it by. */
    item: string
    runs: number
    succeeded: number
    failed: number
    skipped: number
    /** Succeeded over succeeded and failed; null when neither happened. */
    uptime: number | null
    p50_duration_ms: number | null
    p95_duration_ms: number | null
    last_status: ItemStatus
    last_run_id: string
    last_at: string | null
    last_failed_at: string | null
    last_error: string | null
    /** The days it ran on, oldest first; a day it did not run on is absent. */
    days: ItemDay[]
}

/** Every element's record over the window. `ItemStats`. */
export interface ItemStats {
    pipeline: string
    window: { start: string; end: string }
    items: ItemHealth[]
}

/** How many days the pipeline screen reads and draws, one bar a day. */
export const ELEMENT_DAYS = 30

/** Read each element's record over the last `days` days. */
export async function readItemStats(code: string, days: number = ELEMENT_DAYS): Promise<ItemStats> {
    return apiJson<ItemStats>(`/pipelines/${encodeURIComponent(code)}/items/$stats?since=${String(days)}d`)
}

/** The steps the record names, in the order the server answered them, which is the document's. */
export function stepsOf(stats: ItemStats): string[] {
    return [...new Set(stats.items.map((row) => row.step))]
}

/** One day as the uptime bar draws it: its date, its share up, and how many failed of how many ran. */
export interface ElementDay {
    date: string
    uptime: number | null
    failed: number
    ran: number
}

/**
 * The last `count` UTC days ending on `today`, oldest first, each read off the element's record.
 *
 * A DAY IT DID NOT RUN ON IS NOT DOWN. It is a day with nothing measured, drawn quiet, and so
 * is a day it was only skipped on: a check that never ran was neither up nor down.
 */
export function elementDays(health: ItemHealth, today: Date, count: number = ELEMENT_DAYS): ElementDay[] {
    const by = new Map(health.days.map((one) => [one.day, one]))
    const days: ElementDay[] = []
    for (let back = count - 1; back >= 0; back--) {
        const moment = new Date(
            Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - back),
        )
        const date = moment.toISOString().slice(0, 10)
        const found = by.get(date)
        const ran = found === undefined ? 0 : found.succeeded + found.failed
        days.push({
            date,
            uptime: found === undefined || ran === 0 ? null : found.succeeded / ran,
            failed: found?.failed ?? 0,
            ran,
        })
    }
    return days
}
