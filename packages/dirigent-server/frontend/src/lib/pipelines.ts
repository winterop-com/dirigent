/**
 * The pipeline resources, as this bundle reads them.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface here mirrors a pydantic model in
 * `dirigent_client.schemas.pipelines` member for member, so a response is used as it arrived and
 * nothing in this app renames a field the server named.
 *
 * A LISTING ROW CARRIES WHAT THE LISTING DRAWS. What fires a pipeline and how its last run went
 * are counted by the same query that reads the page, so a screen of fifty pipelines is one
 * request and not fifty-one.
 *
 * THERE IS NO SEPARATE PLAN VERB. `POST /pipelines/$apply?dry_run=true` is the plan, and the
 * same call without the flag is the apply -- so what a dialog previews and what it then does are
 * the same request, and cannot disagree about what a document means.
 */

import { apiJson, apiSend, type JsonMap, type Page } from '@/lib/api'
import { formatRelative } from '@/lib/format'
import { titleOf } from '@/lib/identity'
import { PAGE } from '@/lib/paging'
import type { RunWindow } from '@/lib/run-window'
import type { RunPriority } from '@/lib/runs'
import type { RunStatus } from '@/lib/status'

/** How the newest run of a pipeline went. `LastRun`. */
export interface LastRun {
    id: string
    status: RunStatus
    started_at: string | null
    finished_at: string | null
    /** The step whose first failed attempt that run holds, when it did not end well. */
    failed_step: string | null
}

/** A pipeline as a listing shows it. `PipelineOut`. */
export interface PipelineOut {
    id: string
    /** The key this pipeline is addressed by: in URLs, in documents, and in every reference. */
    code: string
    /** What to call it on screen, when somebody gave it something to be called. */
    name: string | null
    description: string | null
    /** What the current document says this pipeline is for, in the order it wrote them. */
    tags: string[]
    active: boolean
    current_version: number | null
    active_runs: number
    schedules: number
    webhooks: number
    last_run: LastRun | null
    created_at: string
    updated_at: string
}

/** A pipeline plus the document its current version holds. `PipelineDetail`. */
export interface PipelineDetail extends PipelineOut {
    document: JsonMap | null
}

/** One immutable version, its digest, and where it came from. `PipelineVersionOut`. */
export interface PipelineVersionOut {
    id: string
    version: number
    digest: string
    provenance_source: string
    provenance_ref: string | null
    applied_by: string | null
    created_at: string
}

/** What starting a run returns: the run id, or why nothing started. `RunAccepted`. */
export interface RunAccepted {
    run_id: string | null
    status: string
    detail: string | null
}

/** One problem with a document, addressed at the place in it that is wrong. `ValidationIssue`. */
export interface ValidationIssue {
    /** A dotted document path such as `steps.push.config.method`. */
    location: string
    message: string
}

/** What applying a document would do to the instance. `PlanAction`. */
export type PlanAction = 'create' | 'update' | 'unchanged' | 'invalid'

/** What changed between the current version and the document being applied. `DiffSummary`. */
export interface DiffSummary {
    steps_added: string[]
    steps_removed: string[]
    steps_changed: string[]
    params_changed: boolean
    triggers_changed: boolean
    settings_changed: boolean
}

/** What applying a document would do, before anything is written. `PipelinePlan`. */
export interface PipelinePlan {
    code: string
    action: PlanAction
    digest: string
    current_version: number | null
    next_version: number | null
    issues: ValidationIssue[]
    diff: DiffSummary | null
}

/** What applying a document did to its triggers. `Materialized`. */
export interface Materialized {
    schedules_created: string[]
    schedules_updated: string[]
    schedules_removed: string[]
    webhooks_created: string[]
    webhooks_updated: string[]
    webhooks_removed: string[]
}

/** The outcome of an apply, or of the dry run that plans one. `ApplyResult`. */
export interface ApplyResult {
    plan: PipelinePlan
    pipeline_id: string | null
    version: number | null
    dry_run: boolean
    triggers: Materialized
}

/**
 * The order the pipelines listing reads in: by the title each row is headed with.
 *
 * THE ORDER IS THE ONE ON SCREEN. The listing arrives in code order, and a screen headed by
 * names but ordered by codes reads as no order at all -- so the rows are put in the order of
 * the string somebody is actually scanning, without case, because nobody scans by case. Two
 * rows may title the same, and the code breaks that tie: it is the one thing no two rows share.
 */
export function byTitle(left: PipelineOut, right: PipelineOut): number {
    const compared = titleOf(left).localeCompare(titleOf(right), undefined, { sensitivity: 'base' })
    return compared === 0 ? left.code.localeCompare(right.code) : compared
}

/**
 * The tags an address asks a listing for, each one once, in the order it named them.
 *
 * A HAND-EDITED ADDRESS OPENS THE LISTING RATHER THAN BREAKING IT. Whatever a tag is not --
 * a shout, a space, an empty repeat -- is normalised or dropped here, so what the chips above
 * the table say is what the request asked for.
 */
export function tagsFromQuery(query: URLSearchParams): string[] {
    return [...new Set(query.getAll('tag').map((tag) => tag.trim().toLowerCase()))].filter(
        (tag) => tag !== '',
    )
}

/**
 * Where one page of the pipelines listing is read from.
 *
 * A tag is a question put to the server, not a squint at the rows already loaded: the API
 * takes `tag` and repeats it to mean and, so choosing a second one narrows the listing and
 * pages through what it narrowed to rather than through everything.
 */
export function pipelinesPath(
    after: string | null,
    tags: readonly string[] = [],
    limit: number = PAGE,
): string {
    const query = new URLSearchParams({ limit: String(limit) })
    if (after !== null) query.set('after', after)
    for (const tag of tags) query.append('tag', tag)
    return `/pipelines?${query.toString()}`
}

/** Read one page of pipelines, in code order, narrowed to every tag that was chosen. */
export function readPipelines(
    after: string | null,
    tags: readonly string[] = [],
    limit: number = PAGE,
): Promise<Page<PipelineOut>> {
    return apiJson<Page<PipelineOut>>(pipelinesPath(after, tags, limit))
}

/** Every tag a set of rows wears, once each, in the order a filter menu offers them. */
export function tagsPresent(rows: readonly PipelineOut[]): string[] {
    return [...new Set(rows.flatMap((row) => row.tags))].toSorted((left, right) => left.localeCompare(right))
}

/** How many pages of pipelines a name lookup walks before it stops asking. */
const NAMES_PAGE_LIMIT = 20

/**
 * Every pipeline this instance holds, up to the page limit a walk stops asking at.
 *
 * A PICKER OFFERS WHAT THERE IS. The listing screens page as somebody scrolls, but a control
 * that offers one pipeline out of all of them has to hold all of them to search across, and a
 * corpus is dozens of rows.
 */
export async function readAllPipelines(): Promise<PipelineOut[]> {
    const rows: PipelineOut[] = []
    let after: string | null = null
    for (let page = 0; page < NAMES_PAGE_LIMIT; page += 1) {
        // A cursor walk is sequential by definition: the next page is named by this one.
        // oxlint-disable-next-line no-await-in-loop
        const answer: Page<PipelineOut> = await readPipelines(after)
        rows.push(...answer.items)
        after = answer.next
        if (after === null) break
    }
    return rows
}

/**
 * What every pipeline is called, keyed by the code it is addressed by.
 *
 * A RUN ROW CARRIES A CODE AND NOTHING ELSE. `RunOut.pipeline` is the code, so a screen that
 * heads a run by its pipeline the way every other screen heads one -- the name where there is
 * one -- has to read the names, and this is that read. It is one walk for the whole listing
 * rather than a lookup per row.
 *
 * A CODE THIS DID NOT REACH IS STILL DRAWN. The map answers nothing for a pipeline past the
 * walk, and `titleOf` heads that row with its code, which is what the row said before.
 */
export async function readPipelineNames(): Promise<Map<string, string | null>> {
    return new Map((await readAllPipelines()).map((row) => [row.code, row.name]))
}

/**
 * The tags a filter menu offers, which is the union of what this instance's pipelines wear.
 *
 * THE UNION IS BUILT HERE AND NOT COUNTED BY THE SERVER. There is no endpoint that tallies an
 * instance's tags, deliberately: a corpus is dozens of rows, and the listing already carries
 * what each one wears.
 *
 * IT IS ITS OWN WALK, and not the rows the screen is showing, because choosing a tag narrows
 * the listing on the server -- so a menu built from what came back would drop every tag those
 * pipelines do not also wear, including the ones somebody would switch to next.
 */
export async function readTagsOffered(): Promise<string[]> {
    return tagsPresent(await readAllPipelines())
}

/**
 * The parameter schema a document declares, which a form of its parameters is built from.
 *
 * A document with no `params` key, or one holding something that is not an object, has no form
 * to draw: the reading is null rather than an empty schema, so a caller says "takes none"
 * rather than drawing a box with nothing in it.
 */
export function paramsOf(document: JsonMap | null): JsonMap | null {
    const params = document?.params
    if (params === null || params === undefined || typeof params !== 'object' || Array.isArray(params))
        return null
    return params as JsonMap
}

/** The priority a document's own runs are claimed at, which every trigger on it may override. */
export function priorityOf(document: JsonMap | null): RunPriority {
    const priority = document?.priority
    return priority === 'low' || priority === 'high' ? priority : 'normal'
}

/** Read a pipeline and the document its current version holds. */
export function readPipeline(code: string): Promise<PipelineDetail> {
    return apiJson<PipelineDetail>(`/pipelines/${encodeURIComponent(code)}`)
}

/** Read a pipeline's versions, newest first. */
export function readVersions(code: string, limit = 5): Promise<Page<PipelineVersionOut>> {
    return apiJson<Page<PipelineVersionOut>>(
        `/pipelines/${encodeURIComponent(code)}/versions?limit=${String(limit)}`,
    )
}

/** Read the JSON Schema a document is written against, composed with this instance's catalog. */
export function readDocumentSchema(): Promise<JsonMap> {
    return apiJson<JsonMap>('/schema/document')
}

/**
 * Start an ad hoc run of a pipeline with these parameters.
 *
 * This API has no verb that repeats a particular run: `$run` is what an ad hoc start is, and a
 * re-run is that call carrying the parameters the finished run was given. It runs the
 * pipeline's current version, which is not necessarily the version the run being repeated
 * pinned, so the screen says which version it is about to run.
 *
 * A window is a fact about a run rather than about a pipeline, so a run given one carries both
 * ends and a run given none carries neither field.
 */
export function startRun(
    pipeline: string,
    params: JsonMap,
    logLevels: Record<string, string> | null = null,
    window: RunWindow | null = null,
): Promise<RunAccepted> {
    return apiSend<RunAccepted>(`/pipelines/${encodeURIComponent(pipeline)}/$run`, 'POST', {
        params,
        ...(logLevels === null ? {} : { log_levels: logLevels }),
        ...(window === null ? {} : window),
    })
}

/** The step definitions in a pipeline document, or none when the document has no steps. */
export function stepsOf(document: JsonMap | null): Record<string, JsonMap> {
    const steps = document?.steps
    if (steps === null || steps === undefined || typeof steps !== 'object' || Array.isArray(steps)) return {}
    return steps as Record<string, JsonMap>
}

/** Send a whole document to be validated against this instance and committed, or only planned. */
export function applyPipeline(document: JsonMap, dryRun: boolean): Promise<ApplyResult> {
    return apiSend<ApplyResult>(`/pipelines/$apply${dryRun ? '?dry_run=true' : ''}`, 'POST', {
        document,
        source: 'api',
    })
}

/** What fires a pipeline on its own, in words, which is what the glyphs are titled with. */
export function triggerSummary(row: Pick<PipelineOut, 'schedules' | 'webhooks'>): string {
    const parts = [count(row.schedules, 'schedule'), count(row.webhooks, 'webhook')].filter(
        (part) => part !== null,
    )
    if (parts.length === 0) return 'nothing fires this on its own'
    return parts.join(' and ')
}

/**
 * What the pipelines table says when it has nothing in it.
 *
 * A tag is a question put to the server, so a listing emptied by one has nothing to do with a
 * listing that was empty anyway, and saying "no pipelines yet" to somebody who just chose a tag
 * would be a lie about the instance. Two tags narrow, so the note says both.
 */
export function emptyNote(loaded: number, tags: readonly string[]): string {
    if (loaded > 0) return 'No loaded pipeline matches that.'
    if (tags.length === 1) return `No pipeline is tagged ${tags[0]}.`
    if (tags.length > 1) return `No pipeline wears all of ${tags.join(', ')}.`
    return 'No pipelines.'
}

/** A count and the thing counted, or nothing at all when there are none. */
function count(many: number, thing: string): string | null {
    if (many === 0) return null
    return `${String(many)} ${thing}${many === 1 ? '' : 's'}`
}

/** How a pipeline's last run reads in the listing: a state, when it was, and what went wrong. */
export interface LastRunView {
    /** A `RunStatus`, which indexes the token the dot is drawn in. */
    status: RunStatus
    /** When it ended, or when it started while it has not ended. */
    when: string
    /** The instant behind that reading, for the element's title. */
    instant: string | null
    failedStep: string | null
}

/** What the last-run cell draws, or nothing for a pipeline that has never run. */
export function lastRunView(last: LastRun | null, now: number = Date.now()): LastRunView | null {
    if (last === null) return null
    const instant = last.finished_at ?? last.started_at
    return {
        status: last.status,
        when: instant === null ? 'not started' : formatRelative(instant, now),
        instant,
        failedStep: last.failed_step,
    }
}

/** Whether a pipeline is one the instance no longer runs, and what to call that. */
export function retirement(row: PipelineOut): string | null {
    return row.active ? null : 'deactivated'
}
