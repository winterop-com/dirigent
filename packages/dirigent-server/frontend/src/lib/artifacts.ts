/**
 * What a run left behind: each step's stored output, and the run's own report document.
 *
 * THE FIELD NAMES ARE THE WIRE'S. `ArtifactOut` mirrors the pydantic model in
 * `dirigent_client.schemas.runs` member for member.
 *
 * THE REPORT DOCUMENT IS ONE ROW OF THAT LISTING, and it is the run-level markdown one: a
 * step's output carries the step's name, so an artifact with no step name and `text/markdown`
 * for a content type is the document the engine rendered when the run settled. There is at
 * most one of them per run.
 *
 * AN ARTIFACT'S CONTENT IS READ, NEVER GUESSED FROM ITS URI. A row that inlined has no uri at
 * all and one that went to storage names a location this browser cannot reach, so
 * `GET /artifacts/{id}` is the only way to the content -- as text through `apiText`, or as the
 * href a download link carries.
 */

import { apiJson, apiText, apiUrl, type Page } from '@/lib/api'
import { PAGE } from '@/lib/paging'

/** The content type the run's report document is stored as. `MARKDOWN_CONTENT_TYPE` in core. */
export const MARKDOWN_CONTENT_TYPE = 'text/markdown'

/** One artifact a run left behind. `ArtifactOut`. */
export interface ArtifactOut {
    id: string
    /** The step whose output this is, or null when the artifact belongs to the run itself. */
    step_name: string | null
    content_type: string | null
    size_bytes: number | null
    /** Where the content was written, when it was too large to inline on the row. */
    uri: string | null
    created_at: string
}

/** How many pages of a run's artifacts a walk asks for before it stops. */
const ARTIFACTS_PAGE_LIMIT = 20

/** Where one page of a run's artifacts is read from. */
export function artifactsPath(runId: string, after: string | null, limit: number = PAGE): string {
    const query = new URLSearchParams({ limit: String(limit) })
    if (after !== null) query.set('after', after)
    return `/runs/${encodeURIComponent(runId)}/artifacts?${query.toString()}`
}

/**
 * Every artifact one run holds, up to the page limit a walk stops asking at.
 *
 * A run's artifacts are one per stored output plus the report document, so the whole listing is
 * what a panel draws rather than a page of it with a cursor under it.
 */
export async function readArtifacts(runId: string): Promise<ArtifactOut[]> {
    const rows: ArtifactOut[] = []
    let after: string | null = null
    for (let page = 0; page < ARTIFACTS_PAGE_LIMIT; page += 1) {
        // A cursor walk is sequential by definition: the next page is named by this one.
        // oxlint-disable-next-line no-await-in-loop
        const answer: Page<ArtifactOut> = await apiJson<Page<ArtifactOut>>(artifactsPath(runId, after))
        rows.push(...answer.items)
        after = answer.next
        if (after === null) break
    }
    return rows
}

/** Where one artifact's own content is read. */
export function artifactPath(id: string): string {
    return `/artifacts/${encodeURIComponent(id)}`
}

/**
 * The href a download link carries for one artifact.
 *
 * The prefix is the one the instance answered `GET /config.json` with, because this bundle
 * cannot know at build time where the versioned API was mounted -- a link is an href rather
 * than a fetch, so the composition `apiFetch` does for a read is done here instead.
 */
export function artifactUrl(prefix: string, id: string): string {
    return apiUrl(prefix, artifactPath(id))
}

/** One artifact's content as text. */
export function readArtifactText(id: string): Promise<string> {
    return apiText(artifactPath(id))
}

/** The run's report document among its artifacts, or null when the run rendered none. */
export function reportArtifact(items: readonly ArtifactOut[]): ArtifactOut | null {
    return items.find((row) => row.step_name === null && row.content_type === MARKDOWN_CONTENT_TYPE) ?? null
}

/** The run's report document: the artifact it is, and the markdown it holds. */
export interface ReportDocument {
    id: string
    markdown: string
}

/**
 * The run's report document, or null when the run rendered none.
 *
 * A run whose document declares no `report:` section renders nothing, which is not a refusal:
 * the listing simply holds no run-level markdown row, and the panel says so. The artifact's id
 * comes back with the text, because the screen that renders it also links it.
 */
export async function readReportDocument(runId: string): Promise<ReportDocument | null> {
    const found = reportArtifact(await readArtifacts(runId))
    if (found === null) return null
    return { id: found.id, markdown: await readArtifactText(found.id) }
}
