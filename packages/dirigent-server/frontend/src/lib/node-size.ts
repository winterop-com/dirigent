/**
 * How wide each box on a pipeline's canvases is drawn, decided from its words before elk places it.
 *
 * A step's code is its identity, so a box is as wide as the longest line it draws -- each line
 * measured in the face the node sets it in, with every glyph and mark that stands on it -- up to
 * `NODE_MAX_WIDTH`, past which a word truncates and carries its whole value on hover.
 */

import { boxWidth, fanOutRoom, GLYPH_WIDTH, NODE_GAP, type Measure } from '@/lib/dag-layout'
import { LABELS } from '@/lib/labels'

/** What a box's title line takes: the title in its face, and a source's glyph before it. */
function titleRow(title: string, named: boolean, source: boolean, measure: Measure): number {
    return measure(title, named ? 'title-sans' : 'title-mono') + (source ? GLYPH_WIDTH + NODE_GAP : 0)
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
