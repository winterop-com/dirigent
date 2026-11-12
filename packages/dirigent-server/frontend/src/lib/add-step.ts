/**
 * What the block picker offers, as pure decisions over the catalog.
 *
 * The groups are the catalog's own: a block declares the group it belongs on, which is what
 * `lib/blocks` shelves the /blocks screen by. A sensor wears a badge saying so and what it means, and a search for
 * `sensor` or `operator` finds every block of that kind. A step's key comes from the block chosen,
 * made unique against the document's own; it is renamed in the step's pane like anything else.
 */

import type { BlockGroup, PipelineBlock } from '@winterop-com/sokkel-ui-graph/blocks'
import { byGroup, type BlockEntry } from '@/lib/blocks'
import { ICONS } from '@/lib/icons'
import { kindFamily, kindLabel } from '@/lib/kinds'
import { LABELS } from '@/lib/labels'

/** What a step key may be, which is `StepName` in dirigent_common. */
const STEP_KEY = /^[a-z][a-z0-9_]*$/

/** The groups the picker lists blocks under: every group the catalog declares, in name order. */
export function pickerGroups(blocks: readonly BlockEntry[]): BlockGroup[] {
    return byGroup(blocks).map(([group]) => ({ id: group, label: group }))
}

/**
 * The catalog as the picker offers it, in id order: each block titled by its id with its summary
 * under it, a sensor badged in its kind's hue, and its kind in the singular and the plural among the words a search
 * finds it by.
 */
export function pickerBlocks(blocks: readonly BlockEntry[]): PipelineBlock[] {
    return blocks
        .toSorted((a, b) => a.id.localeCompare(b.id))
        .map((entry) => ({
            kind: entry.id,
            description: entry.summary,
            group: entry.group,
            icon: ICONS.block,
            badge:
                entry.kind === 'sensor'
                    ? {
                          label: kindLabel(entry.kind),
                          hue: kindFamily(entry.kind),
                          title: LABELS.editor.canvas.sensor_title,
                      }
                    : undefined,
            keywords: [entry.kind, `${entry.kind}s`],
        }))
}

/**
 * The key a step added from the menu takes: the block's own name, made unique.
 *
 * `transform.jq` lands as `jq`, and a second one as `jq_2`. The id's family is dropped because
 * the remainder is what somebody would have typed, and anything the key pattern would refuse --
 * a dot, a dash, a leading digit -- becomes an underscore rather than a document the apply
 * would turn down.
 */
export function stepKeyFor(block: string, taken: readonly string[]): string {
    const base = keyBase(block)
    if (!taken.includes(base)) return base
    for (let suffix = 2; ; suffix += 1) {
        const candidate = `${base}_${String(suffix)}`
        if (!taken.includes(candidate)) return candidate
    }
}

function keyBase(block: string): string {
    const dot = block.indexOf('.')
    const rest = dot === -1 ? block : block.slice(dot + 1)
    const written = rest
        .toLowerCase()
        .replaceAll(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
    if (written === '' || !STEP_KEY.test(written)) return `step_${written}`.replace(/_$/, '')
    return written
}
