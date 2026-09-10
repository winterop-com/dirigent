/**
 * What this instance has installed.
 *
 * ONE READ, AND IT IS NOT THE PROBE. `GET /system/info` is the versioned API's and says what is
 * installed -- version, environment, database, blocks, storage schemes, plugins, and what every
 * configured connection said when it was last checked. It opens no connection itself: a read
 * made on every page load must not run anyone's connect timeout. Whether the process is fit
 * to serve is a different question
 * with a different answer, asked at the root by `lib/server-status`, and there is exactly one
 * reader of it: the corner dot's store, which the settings dialog reads rather than asking a
 * second time.
 */

import { apiJson } from '@/lib/api'

/** What one configured connection said the last time it was checked. `ConnectionHealth`. */
export interface ConnectionHealth {
    code: string
    name: string | null
    kind: string
    last_check_at: string | null
    last_check_healthy: boolean | null
    last_check_detail: string | null
}

/** Everything this instance is. `SystemInfo`. */
export interface SystemInfo {
    name: string
    version: string
    environment: string
    /** The dialect in use, such as `sqlite` or `postgresql`. */
    database: string
    checked_at: string
    plugins: string[]
    blocks: number
    storage_schemes: string[]
    notifiers: string[]
    connection_kinds: string[]
    workers_live: number
    unsafe_blocks_enabled: string[]
    secrets_configured: boolean
    connections: ConnectionHealth[]
}

/** Read what this instance is. */
export function readSystemInfo(): Promise<SystemInfo> {
    return apiJson<SystemInfo>('/system/info')
}
