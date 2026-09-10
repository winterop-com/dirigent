/**
 * The document in front of somebody, which is not yet the document the instance holds.
 *
 * THE EDITOR IS LOCAL UNTIL IT IS APPLIED. A pipeline is a versioned document and the only way
 * to change one is to apply a whole new one, so this screen edits a copy: the graph, the step
 * form and the source pane are three readings of the same local document, and the count of
 * unapplied edits is the difference between it and the version the instance holds.
 *
 * IT IS A MODULE STORE because three unrelated parts of the screen read it -- a node on the
 * canvas, a chip in the topbar, a pane in the right panel -- and none of them is inside the
 * others. `lib/store` imports no React, so every decision here is exercised in plain Node.
 *
 * THE SOURCE PANE MAY HOLD TEXT THAT IS NOT A DOCUMENT, and while it does, the local document
 * is the last one that parsed. Nothing else may write to it in that state: a form quietly
 * replacing the text somebody is halfway through fixing is worse than a form that says it
 * cannot.
 */

import { parse, stringify } from 'yaml'

import type { JsonMap } from '@/lib/api'
import { headingOf, type Heading } from '@/lib/identity'
import { createStore } from '@/lib/store'

/** What this screen holds for one pipeline. */
export interface DocumentState {
    /** The pipeline the document is of, by its code. Loading another replaces the whole state. */
    code: string | null
    /** The document as the instance holds it, which is what an edit is measured against. */
    applied: JsonMap | null
    /** The document as edited here, which is what the graph draws and what an apply sends. */
    local: JsonMap | null
    /** What the source pane holds while it does not parse, or null when the two agree. */
    draft: string | null
    /** Why the draft is not a document. */
    parseError: string | null
}

const NOTHING: DocumentState = { code: null, applied: null, local: null, draft: null, parseError: null }

export const documentStore = createStore<DocumentState>(NOTHING)

/**
 * The code a document nothing has applied yet is held under, which is the word its route uses.
 *
 * `/pipelines/$new` is the editor with no pipeline behind it, and the store is keyed by the same
 * word so a stale state from one pipeline cannot be read as this document's.
 */
export const NEW_DOCUMENT = 'new'

/** The code the skeleton gives itself, which is the first thing somebody changes. */
export const NEW_CODE = 'my-pipeline'

/** Take a pipeline's stored document as the document being edited. */
export function loadDocument(code: string, applied: JsonMap | null): void {
    documentStore.set({ code, applied, local: applied === null ? null : clone(applied), draft: null, parseError: null })
}

/** The smallest document an apply accepts: what it is, what it is called, and room for steps. */
export function newDocument(): JsonMap {
    return {
        format: 'dirigent/v1',
        kind: 'pipeline',
        code: NEW_CODE,
        name: 'My pipeline',
        steps: {},
    }
}

/**
 * Start a document the instance holds no version of.
 *
 * There is nothing applied to measure an edit against, so everything in it is unwritten until
 * the first apply -- which is what makes that apply a create rather than an update.
 */
export function startDocument(source?: string): void {
    documentStore.set({
        code: NEW_DOCUMENT,
        applied: null,
        local: newDocument(),
        draft: null,
        parseError: null,
    })
    if (source !== undefined) writeSource(source)
}

/** Forget the document. A screen calls this as it unmounts, so the next one starts clean. */
export function forgetDocument(): void {
    documentStore.set(NOTHING)
}

/**
 * Change the local document, unless the source pane is holding text that does not parse.
 *
 * Answers whether the change was made, so a caller can say why it was not.
 */
export function changeDocument(change: (document: JsonMap) => JsonMap): boolean {
    const state = documentStore.get()
    if (state.local === null || state.parseError !== null) return false
    const next = change(state.local)
    // A change that changed nothing publishes nothing: drawing an edge the document already
    // has is a gesture, not an edit, and it must not count as one.
    if (next === state.local) return true
    documentStore.set({ ...state, local: next })
    return true
}

/**
 * Take the source pane's text as the document.
 *
 * Text that does not parse is kept as the draft and the local document is left alone, so the
 * other tabs go on showing the last document there was rather than nothing.
 */
export function writeSource(text: string): void {
    const state = documentStore.get()
    const read = fromYaml(text)
    if (!read.ok) {
        documentStore.set({ ...state, draft: text, parseError: read.message })
        return
    }
    documentStore.set({ ...state, local: read.document, draft: null, parseError: null })
}

/** Throw the local edits away and go back to what the instance holds. */
export function revertDocument(): void {
    const state = documentStore.get()
    documentStore.set({
        ...state,
        local: state.applied === null ? null : clone(state.applied),
        draft: null,
        parseError: null,
    })
}

/** The step definitions in a document, or none when it has no steps. */
export function stepsIn(document: JsonMap | null): Record<string, JsonMap> {
    const steps = document?.steps
    if (steps === null || steps === undefined || typeof steps !== 'object' || Array.isArray(steps)) return {}
    return steps as Record<string, JsonMap>
}

/** The steps a document declares, in the order it declares them. */
export function stepNames(document: JsonMap | null): string[] {
    return Object.keys(stepsIn(document))
}

/** The block one step runs, or null when the step does not name one. */
export function blockOf(document: JsonMap | null, step: string): string | null {
    const value = stepsIn(document)[step]?.block
    return typeof value === 'string' ? value : null
}

/**
 * One step's display name, or null when the document gives it none.
 *
 * A step is referenced by its key -- in `depends_on`, in a run's events, in every log line --
 * and this is the string beside that key rather than instead of it.
 */
export function stepName(document: JsonMap | null, step: string): string | null {
    const value = stepsIn(document)[step]?.name
    return typeof value === 'string' && value.trim() !== '' ? value : null
}

/** How one step is headed: its name over its key, or its key alone when it has no name. */
export function stepHeading(document: JsonMap | null, step: string): Heading {
    return headingOf({ code: step, name: stepName(document, step) })
}

/** One step's config, which is the map a block's own form is built over. */
export function configOf(document: JsonMap | null, step: string): JsonMap {
    const config = stepsIn(document)[step]?.config
    if (config === null || config === undefined || typeof config !== 'object' || Array.isArray(config)) return {}
    return config as JsonMap
}

/** The steps one step waits for. */
export function dependsOn(document: JsonMap | null, step: string): string[] {
    const value = stepsIn(document)[step]?.depends_on
    return Array.isArray(value) ? value.map((one) => String(one)) : []
}

/** What a step's `for_each` amounts to: whether it fans out, and over how many items. */
export interface FanOut {
    fanOut: boolean
    /** How many items the list holds, or null where it is an expression a run resolves. */
    items: number | null
}

/** Whether one step fans out, and over how many items where the document says so literally. */
export function fanOutOf(document: JsonMap | null, step: string): FanOut {
    const value = stepsIn(document)[step]?.for_each
    if (value === null || value === undefined) return { fanOut: false, items: null }
    return { fanOut: true, items: Array.isArray(value) ? value.length : null }
}

/** Every edge in a document, pointing from prerequisite to dependent. */
export function edgesIn(document: JsonMap | null): [string, string][] {
    const known = new Set(stepNames(document))
    return stepNames(document).flatMap((name) =>
        dependsOn(document, name)
            .filter((dependency) => known.has(dependency))
            .map((dependency): [string, string] => [dependency, name]),
    )
}

/** One step's config as the one muted line a node has room for, or null when it has nothing. */
export function configSummary(config: JsonMap): string | null {
    const parts = Object.entries(config)
        .filter(([, value]) => value !== null && typeof value !== 'object')
        .map(([key, value]) => `${key}: ${String(value)}`)
    return parts.length === 0 ? null : parts.join(' · ')
}

/** A document with one step's config replaced. */
export function withStepConfig(document: JsonMap, step: string, config: JsonMap): JsonMap {
    return withStepMember(document, step, 'config', config)
}

/** A document with one step's display name set, or without it when the box was emptied. */
export function withStepName(document: JsonMap, step: string, name: string | null): JsonMap {
    const trimmed = name === null ? '' : name.trim()
    return withStepMember(document, step, 'name', trimmed === '' ? undefined : trimmed)
}

/** A document with one step's prerequisites replaced. */
export function withDependsOn(document: JsonMap, step: string, names: string[]): JsonMap {
    return withStepMember(document, step, 'depends_on', names)
}

/**
 * A document with one more step in it, running one block and depending on nothing.
 *
 * A step is added at the end. The canonical order is topological and the server decides it at
 * apply, so what this writes is the order somebody added things in, and the export re-orders it.
 */
export function withStep(document: JsonMap, name: string, block: string): JsonMap {
    return { ...document, steps: { ...stepsIn(document), [name]: { block } } }
}

function withStepMember(document: JsonMap, step: string, member: string, value: unknown): JsonMap {
    const steps = stepsIn(document)
    const existing = steps[step]
    if (existing === undefined) return document
    const changed = { ...existing, [member]: value }
    if (value === undefined || (Array.isArray(value) && value.length === 0)) delete changed[member]
    return { ...document, steps: { ...steps, [step]: changed } }
}

/**
 * What a document's `report:` section asks for.
 *
 * The three answers are the section's three states: no section at all, a section with no
 * template, and a section carrying one. An empty section is not the absence of a section --
 * `report: {}` is what asks for the built-in document.
 */
export interface ReportSection {
    declared: boolean
    /** The document's own template, or null where the section asks for the built-in one. */
    template: string | null
}

/** The report section a document declares. */
export function reportIn(document: JsonMap | null): ReportSection {
    const found = document?.report
    if (found === null || found === undefined || typeof found !== 'object' || Array.isArray(found)) {
        return { declared: false, template: null }
    }
    const template = (found as JsonMap).template
    return { declared: true, template: typeof template === 'string' ? template : null }
}

/** A document that renders a report when a run of it settles: its own template, or the built-in one. */
export function withReport(document: JsonMap, template: string | null): JsonMap {
    return { ...document, report: template === null ? {} : { template } }
}

/** A document that renders no report at all. */
export function withoutReport(document: JsonMap): JsonMap {
    const next = { ...document }
    delete next.report
    return next
}

/** What has been edited and not applied. */
export interface DocumentEdits {
    /** Steps that were added, removed, or changed. */
    steps: string[]
    /** Top-level keys other than the steps that differ: the code, the name, the params. */
    fields: string[]
    /** How many separate things differ, which is what the topbar chip counts. */
    count: number
}

const NO_EDITS: DocumentEdits = { steps: [], fields: [], count: 0 }

/**
 * What one document changes about another.
 *
 * A step counts once however many of its members moved: what a reader is being told is which
 * steps they have touched, and a node on the canvas is marked from the same list.
 */
export function editsIn(applied: JsonMap | null, local: JsonMap | null): DocumentEdits {
    if (local === null) return NO_EDITS
    if (applied === null) return { steps: stepNames(local), fields: [], count: stepNames(local).length }

    const before = stepsIn(applied)
    const after = stepsIn(local)
    const names = [...new Set([...Object.keys(before), ...Object.keys(after)])]
    const steps = names.filter((name) => stable(before[name]) !== stable(after[name]))

    const keys = [...new Set([...Object.keys(applied), ...Object.keys(local)])].filter((key) => key !== 'steps')
    const fields = keys.filter((key) => stable(applied[key]) !== stable(local[key]))

    return { steps, fields, count: steps.length + fields.length }
}

/** Whether one step differs from the version the instance holds. */
export function stepEdited(edits: DocumentEdits, step: string): boolean {
    return edits.steps.includes(step)
}

/** How the topbar chip and the status bar say how much is unapplied. */
export function editsLabel(edits: DocumentEdits): string {
    return `${String(edits.count)} unapplied edit${edits.count === 1 ? '' : 's'}`
}

/** How much of a step's key the panel's tab has room for before the strip starts moving. */
const STEP_TAB_BUDGET = 14

/**
 * What the step tab is called: the chosen step's key, or the bare word when nothing is chosen.
 *
 * The key is what `depends_on` and every log line reference, so it is what the tab carries. A
 * key past the budget is cut rather than allowed to widen the strip under somebody's pointer.
 */
export function stepTabLabel(step: string | null): string {
    if (step === null) return 'Step'
    const shown = step.length > STEP_TAB_BUDGET ? `${step.slice(0, STEP_TAB_BUDGET - 1)}…` : step
    return `Step · ${shown}`
}

/**
 * Which button an apply wears.
 *
 * THE IDENTITY COLOUR IS SPENT ON WHAT WOULD DO SOMETHING. An apply of a document the instance
 * already holds writes nothing, so it stands beside Validate rather than shouting over it; a
 * document that differs, and one no version exists of at all, is the action on the screen.
 */
export function applyVariant(edits: DocumentEdits, unwritten: boolean): 'default' | 'outline' {
    return unwritten || edits.count > 0 ? 'default' : 'outline'
}

/**
 * The order a document's top-level keys are written in, which is the order the examples use.
 *
 * A key not named here keeps its place after these, in the order the document holds it.
 */
const DOCUMENT_KEYS = ['format', 'kind', 'code', 'name', 'description', 'tags', 'params', 'steps']

/**
 * The local document as YAML.
 *
 * THIS IS NOT THE CANONICAL EXPORT. `GET /pipelines/{code}/$export` is, and it orders the steps
 * topologically. What this renders is the document as it stands here, with its steps in the
 * order it holds them, so what somebody edits and what they read back are the same thing. An
 * apply is what canonicalises it.
 *
 * IT ALWAYS SAYS WHAT IT IS. A stored document can come back without `format` and with its keys
 * in whatever order the database held them, and a pane opening on `code:` reads as a fragment
 * rather than a document, so the two words that say what this is are written first and the rest
 * follow in the order an author writes them.
 */
export function toYaml(document: JsonMap): string {
    const said: JsonMap = { format: 'dirigent/v1', kind: 'pipeline', ...document }
    const ordered: JsonMap = {}
    for (const key of DOCUMENT_KEYS) {
        if (said[key] !== undefined) ordered[key] = said[key]
    }
    for (const [key, value] of Object.entries(said)) {
        if (!(key in ordered)) ordered[key] = value
    }
    return stringify(ordered, { indent: 2, lineWidth: 100 })
}

/** Read the source pane's text as a document, or say why it is not one. */
export function fromYaml(text: string): { ok: true; document: JsonMap } | { ok: false; message: string } {
    let parsed: unknown
    try {
        parsed = parse(text) as unknown
    } catch (error) {
        return { ok: false, message: error instanceof Error ? error.message : 'that is not YAML' }
    }
    if (parsed === null || parsed === undefined) return { ok: false, message: 'the document is empty' }
    if (typeof parsed !== 'object' || Array.isArray(parsed)) {
        return { ok: false, message: 'a document is a mapping of keys, not a single value' }
    }
    return { ok: true, document: parsed as JsonMap }
}

/** A copy nothing else holds a reference into, so an edit cannot reach the applied document. */
function clone(document: JsonMap): JsonMap {
    return JSON.parse(JSON.stringify(document)) as JsonMap
}

/** One value as a string that is the same for two values that are the same. */
function stable(value: unknown): string {
    return JSON.stringify(value, (_key, item: unknown) => {
        if (item === null || typeof item !== 'object' || Array.isArray(item)) return item
        const mapping = item as JsonMap
        return Object.fromEntries(Object.keys(mapping).toSorted().map((key) => [key, mapping[key]]))
    })
}
