import { expect, test, type Locator, type Page } from '@playwright/test'

import { LABELS } from '../src/lib/labels.ts'
import { applyDocument, signIn } from './support.ts'

/**
 * A dialog caps itself and its body scrolls, whatever the body holds.
 *
 * WHAT THIS CATCHES AND NOTHING ELSE DOES. A block between a dialog's header and its footer that
 * declares a height puts a second scroll inside the first and cuts its own content off at a line
 * nothing drew -- and where the surface around it declares no height either, the verbs at the
 * foot go off the bottom of the window with nothing to scroll to reach them. Three surfaces had
 * it: the run dialog capped its parameter form at `50vh`, and both trigger dialogs capped a
 * payload mapping and a pinned-parameters form at `32vh`. Every gate passed the whole time.
 *
 * THE FORM HAS TO BE LONGER THAN THE SCREEN OR THERE IS NOTHING TO SEE. A pipeline with five
 * parameters fits, so the fixture declares eighteen; a webhook's mapping draws a row per
 * parameter and a schedule's pinned box draws the same form again, so one fixture is all three.
 *
 * EVERY PARAMETER IS A SCALAR. An array or a bare object is drawn as a code pane, which brings
 * an editor and the editor's own scrolling into the very thing being measured.
 *
 * 1024x768 IS THE BINDING VIEWPORT. The two review sizes are 1024x768 and 390x844, so the phone
 * is 76px taller: anything vertical fails on the short desktop first.
 *
 * MEASURED AGAINST THE SCROLLER, NOT THE DIALOG. A control cut off by a fold is still inside the
 * dialog's own box, so what is read is the window the verbs have to be inside, and which part
 * between the header and the footer is the one that scrolls.
 *
 * `docs/ui-conventions.md`, "A surface is inset once, and 16px is the inset".
 */

/** The two sizes every UI change is reviewed at; the short one is the one that fails first. */
const VIEWPORTS = [
    { width: 1024, height: 768 },
    { width: 390, height: 844 },
]

/** Both palettes, because a dialog's chrome and its type differ between them. */
const MODES = ['dark', 'light']

/** Wide and tall enough that every toolbar verb is drawn rather than folded behind a menu. */
const OPENING = { width: 1280, height: 800 }

const PIPELINE = 'e2e-long-form'
const TITLE = 'A form longer than the screen'

/** The parameter this fixture's form ends on, which is what says the form was drawn whole. */
const LAST = 'field_15'

/**
 * One step, and a parameter schema long enough that the form it draws outgrows a short desktop.
 *
 * Nothing references the parameters: apply checks that every `${...}` a step writes resolves
 * against the schema, not that every parameter is read, so the step stays the simplest one that
 * applies.
 */
function longForm(): Record<string, unknown> {
    const properties: Record<string, unknown> = {
        dataset: {
            type: 'string',
            enum: ['climate', 'population', 'incidence'],
            default: 'climate',
            description: 'Which dataset to process.',
        },
        batch_size: { type: 'integer', minimum: 1, maximum: 10_000, default: 500 },
        dry_run: { type: 'boolean', default: false, description: 'Write nothing downstream.' },
    }
    for (let at = 0; at < 16; at += 1) {
        properties[`field_${String(at).padStart(2, '0')}`] = {
            type: 'string',
            description: `What field ${String(at)} of the record carries.`,
        }
    }
    return {
        format: 'dirigent/v1',
        kind: 'pipeline',
        code: PIPELINE,
        name: TITLE,
        description: 'Eighteen parameters, so every surface that draws them is longer than a screen.',
        requires: { blocks: ['transform.jq'] },
        params: { type: 'object', required: ['field_00'], properties },
        steps: {
            dates: { block: 'transform.jq', config: { input: { start: 'a literal' }, program: '.' } },
        },
    }
}

/** What a dialog's layout is, read from the page rather than from the classes that made it. */
interface Layout {
    /** How far the surface's own box falls outside the window; positive is off the screen. */
    surfaceOutside: number
    /** How many parts stand between the header and the footer. The body is meant to be one. */
    partsInTheBody: number
    /** Whether that one part is the thing that scrolls. */
    bodyScrolls: boolean
    /** How many of the body's controls sit in a scroller nested inside the body. */
    foldedControls: number
    /** How far the verb at the foot falls outside the window; positive is out of reach. */
    verbOutside: number
}

/** Anything somebody presses, types in or chooses from. It is handed to the page: a constant in
 * this file is not in scope inside an evaluation. */
const CONTROLS = 'input, textarea, select, button, [role="combobox"], [role="switch"], [role="radio"]'

/**
 * Read the whole of a dialog's layout in one pass, so every number is from the same frame.
 *
 * The verb is found by its own text inside the page rather than handed in as a locator, because
 * a second round trip is a second layout.
 */
async function layoutOf(dialog: Locator, verb: string): Promise<Layout> {
    return dialog.evaluate(
        (surface, { wanted, controls }) => {
            const scrolls = (node: Element): boolean => {
                const style = getComputedStyle(node)
                return style.overflowY === 'auto' || style.overflowY === 'scroll'
            }
            /** How far a box falls outside the window, below it or above it; positive is outside. */
            const outside = (box: DOMRect): number =>
                Math.round(Math.max(box.bottom - window.innerHeight, -box.top))

            const header = surface.querySelector('[data-slot="dialog-header"]')
            const footer = surface.querySelector('[data-slot="dialog-footer"]')
            const body = [...surface.children].filter(
                (child) =>
                    child !== header && child !== footer && !child.matches('[data-slot="dialog-close"]'),
            )

            // Every control the body offers, walked up to the scroller it sits in. One that stops at
            // a scroller inside the body is a control behind a fold of its own.
            let folded = 0
            for (const part of body) {
                for (const control of part.querySelectorAll(controls)) {
                    let walk: Element | null = control.parentElement
                    while (walk !== null && walk !== surface) {
                        if (scrolls(walk)) {
                            if (walk !== part) folded += 1
                            break
                        }
                        walk = walk.parentElement
                    }
                }
            }

            const button = [...(footer?.querySelectorAll('button') ?? [])].find(
                (one) => (one.textContent ?? '').trim() === wanted,
            )
            return {
                surfaceOutside: outside(surface.getBoundingClientRect()),
                partsInTheBody: body.length,
                bodyScrolls: body.length === 1 && scrolls(body[0]),
                foldedControls: folded,
                verbOutside: button === undefined ? Number.NaN : outside(button.getBoundingClientRect()),
            }
        },
        { wanted: verb, controls: CONTROLS },
    )
}

/**
 * The layout once it has stopped changing.
 *
 * A VIEWPORT THAT HAS JUST CHANGED IS A LAYOUT STILL SETTLING, and fonts being ready plus a frame
 * is not the end of it: readings taken there came out about 55px wrong. So this reads until two
 * reads in a row agree, and those are the numbers asserted on.
 */
async function settled(dialog: Locator, verb: string): Promise<Layout> {
    let last = ''
    let held: Layout | null = null
    await expect
        .poll(
            async () => {
                const now = await layoutOf(dialog, verb)
                const again = JSON.stringify(now) === last
                last = JSON.stringify(now)
                held = now
                return again
            },
            { intervals: [100, 100, 150, 150, 250, 250, 500], timeout: 15_000 },
        )
        .toBe(true)
    if (held === null) throw new Error('the dialog never settled into a layout')
    return held
}

/**
 * The surface caps, its body is the one part that scrolls, and the verb is on the screen.
 *
 * `verbOutside` is the number the fault was: with no cap on the surface, Run stood below the
 * bottom of the window and nothing scrolled it back.
 */
async function capsAndScrolls(page: Page, dialog: Locator, verb: string, named: string): Promise<void> {
    for (const size of VIEWPORTS) {
        await page.setViewportSize(size)
        const where = `${named} at ${String(size.width)}x${String(size.height)}`
        const layout = await settled(dialog, verb)
        expect(layout.partsInTheBody, `${where}: parts between the header and the footer`).toBe(1)
        expect(layout.bodyScrolls, `${where}: the body is the part that scrolls`).toBe(true)
        expect(layout.foldedControls, `${where}: controls behind a fold of their own`).toBe(0)
        expect(layout.surfaceOutside, `${where}: the surface is off the screen by`).toBeLessThanOrEqual(0)
        expect(layout.verbOutside, `${where}: ${verb} is off the screen by`).toBeLessThanOrEqual(0)
    }
}

/**
 * Open a screen in one palette, at the size every toolbar verb is drawn at.
 *
 * The size is set before the navigation because the editor draws no Run button on a small screen
 * and the triggers header folds its two verbs behind a menu at 1024, so a pass that opened at a
 * review size would have nothing to press.
 */
async function open(page: Page, mode: string, at: string): Promise<void> {
    await page.setViewportSize(OPENING)
    await page.evaluate((theme) => {
        localStorage.setItem('theme', theme)
        localStorage.setItem('dirigent.palette', 'dirigent')
    }, mode)
    await page.goto(at)
}

/** Choose one option in a picker, which is how a pipeline is named to a trigger dialog. */
async function pick(page: Page, field: string, query: string, option: string): Promise<void> {
    const box = page.getByRole('dialog').getByLabel(field, { exact: true })
    await box.fill('')
    await box.fill(query)
    // The list is portalled out of the dialog, so the option is reached on the page.
    await page.getByRole('option', { name: option }).click()
}

test.beforeEach(async ({ page }) => {
    await signIn(page)
    await applyDocument(page.request, longForm())
})

test('a run dialog on a long parameter form keeps Run now on the screen', async ({ page }) => {
    for (const mode of MODES) {
        await open(page, mode, `/pipelines/${PIPELINE}`)
        await page.getByRole('button', { name: LABELS.action.run, exact: true }).click()
        const dialog = page.getByRole('dialog')
        await expect(dialog.getByLabel(LAST, { exact: true })).toBeAttached()
        await capsAndScrolls(page, dialog, LABELS.editor.run.confirm, `the run dialog in ${mode}`)
    }
})

test('a new schedule on a long pinned-parameters form keeps Create on the screen', async ({ page }) => {
    for (const mode of MODES) {
        await open(page, mode, '/triggers')
        await page.getByRole('button', { name: LABELS.triggers.schedule.new, exact: true }).click()
        const dialog = page.getByRole('dialog')
        await pick(page, LABELS.word.pipeline.label, PIPELINE, TITLE)
        await expect(dialog.getByLabel(LAST, { exact: true })).toBeAttached()
        await capsAndScrolls(page, dialog, LABELS.action.create.verb, `the new schedule dialog in ${mode}`)
    }
})

test('a new webhook on a wide payload mapping keeps Create on the screen', async ({ page }) => {
    for (const mode of MODES) {
        await open(page, mode, '/triggers')
        await page.getByRole('button', { name: LABELS.triggers.webhook.new, exact: true }).click()
        const dialog = page.getByRole('dialog')
        await pick(page, LABELS.word.pipeline.label, PIPELINE, TITLE)
        await expect(dialog.getByLabel(LAST, { exact: true })).toBeAttached()
        await capsAndScrolls(page, dialog, LABELS.action.create.verb, `the new webhook dialog in ${mode}`)
    }
})
