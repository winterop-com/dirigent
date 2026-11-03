/**
 * How big each kind of box is drawn, decided from its words before elk places it.
 *
 * A step's code is its identity, so a box is as wide as the longest line it draws -- each line
 * measured in the face the node sets it in, with every glyph, chip and dot that stands on it --
 * up to `NODE_MAX_WIDTH`, past which a word truncates and carries its whole value on hover. A
 * fan-out's elements wrap onto as many lines as they need rather than being cut, and the box is
 * as tall as that.
 */

import {
    boxWidth,
    DOT_WIDTH,
    fanOutRoom,
    GLYPH_WIDTH,
    heightOf,
    NODE_CHROME,
    NODE_GAP,
    NODE_HEIGHT,
    stripLines,
    stripWidth,
    type Measure,
} from '@/lib/dag-layout'
import { headingOf } from '@/lib/identity'
import { counted, LABELS } from '@/lib/labels'
import { emptyStripLabel, type ItemChip, type StepView } from '@/lib/run-detail'

/** What a step's duration takes at the end of its second line, with the gap before it. */
export const DURATION_ROOM = 48

/** The most a fan-out's chips widen a box before they wrap onto another line. */
export const STRIP_ROOM = 240

/** The gap inside a chip, between its dot and its key. */
const CHIP_INNER_GAP = 4

/** What a box's title line takes: the title in its face, and a source's glyph before it. */
function titleRow(title: string, named: boolean, source: boolean, measure: Measure): number {
    return measure(title, named ? 'title-sans' : 'title-mono') + (source ? GLYPH_WIDTH + NODE_GAP : 0)
}

/** How wide one element of a fan-out's strip is drawn. */
export function chipWidth(chip: Pick<ItemChip, 'key' | 'retry'>, measure: Measure): number {
    // A retry counts down every second; its width is reserved at its widest so the box does not.
    const retry =
        chip.retry === null
            ? 0
            : CHIP_INNER_GAP + measure(LABELS.runs.retry_try_in('99', '999'), 'small-sans')
    return DOT_WIDTH + CHIP_INNER_GAP + measure(chip.key, 'small-mono') + retry
}

/** The width and height a run's box is drawn at. */
export function runNodeSize(view: StepView, measure: Measure): { width: number; height: number } {
    const heading = headingOf(view.node)
    const source = view.node.kind === 'source'
    const items = Math.max(view.items, view.node.items_total)
    const count =
        view.node.fan_out && items > 0
            ? NODE_GAP + measure(counted(items, LABELS.runs.node_items)(String(items)), 'small-mono')
            : 0
    // A reply's box is sized for the longer of what it says once settled.
    const what =
        view.node.kind === 'reply' ? `${view.node.block} · ${LABELS.runs.reply.not_sent}` : view.node.block
    const line = heading.code === null ? what : `${heading.code} · ${what}`

    const rows = [
        titleRow(heading.title, heading.named, source, measure) + count + NODE_GAP + DOT_WIDTH,
        measure(line, 'small-mono') + DURATION_ROOM,
    ]
    if (!view.node.fan_out) return { width: boxWidth(rows), height: NODE_HEIGHT }

    const strip = view.strip
    if (strip.kind !== 'chips') {
        const words =
            strip.kind === 'empty'
                ? emptyStripLabel(view)
                : strip.counts
                      .map((one) => LABELS.runs.node_item_count(String(one.count), one.status))
                      .join(' · ')
        return { width: boxWidth([...rows, measure(words, 'small-sans')]), height: heightOf(true) }
    }
    const chips = strip.items.map((chip) => chipWidth(chip, measure))
    // The chips widen a box only so far, and wrap past that, so one wide fan-out does not stretch its rank.
    const width = boxWidth([...rows, Math.min(STRIP_ROOM, stripWidth(chips)), ...chips])
    return { width, height: heightOf(true, stripLines(chips, width - NODE_CHROME)) }
}

/** The width a box on a pipeline's page is drawn at: its title, a fan-out's glyph, and its block. */
export function shapeNodeWidth(
    words: { title: string; named: boolean; line: string },
    source: boolean,
    fanOut: boolean,
    measure: Measure,
): number {
    return boxWidth([
        titleRow(words.title, words.named, source, measure) + (fanOut ? NODE_GAP + GLYPH_WIDTH : 0),
        measure(words.line, 'small-mono'),
    ])
}

/** What a mark on the editor's box takes beside its title: the gap, the word, its padding and edge. */
function markRoom(word: string, measure: Measure): number {
    return NODE_GAP + measure(word, 'small-sans') + 10
}

/**
 * The width a box in the editor is drawn at: its title with the mark it wears or may come to wear,
 * and its line with the fan-out marker at its end.
 *
 * The edited mark's room is held whether or not the step is edited yet, so the first keystroke
 * into a step's config moves no box.
 */
export function documentNodeWidth(
    words: { title: string; named: boolean; line: string },
    marks: { source: boolean; missing: boolean; fanOut: string | null },
    measure: Measure,
): number {
    const mark = markRoom(
        marks.missing ? LABELS.editor.canvas.not_installed : LABELS.editor.canvas.edited,
        measure,
    )
    return boxWidth([
        titleRow(words.title, words.named, marks.source, measure) + mark,
        measure(words.line, 'small-mono') + (marks.fanOut === null ? 0 : fanOutRoom(marks.fanOut, measure)),
    ])
}
