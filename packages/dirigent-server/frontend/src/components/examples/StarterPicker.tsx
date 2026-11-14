import { useMemo } from 'react'

import {
    CommandPalette,
    type PaletteCommand,
    type PaletteGroup,
} from '@winterop-com/sokkel-ui/CommandPalette'
import { useRead } from '@/hooks/use-read'
import {
    readAllExamples,
    readExample,
    readHoldings,
    requirementsOf,
    requirementsSummary,
    shelveStarters,
    starterMatches,
    type ExampleOut,
    type Holdings,
} from '@/lib/examples'
import { headingOf } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { refusalLine, refusalOf } from '@/lib/refusal'
import { copyStarter } from '@/lib/starters'

export const FROM_A_STARTER = LABELS.pipelines.starters.title

export const PICKER_PLACEHOLDER = LABELS.pipelines.starters.placeholder

export const PICKER_EMPTY = LABELS.pipelines.starters.empty

export const PICKER_READING = LABELS.shell.reading

export const PICKER_NONE = LABELS.pipelines.starters.none

/**
 * One starter out of the installed corpus, chosen the way everything else here is chosen.
 *
 * IT IS THE PALETTE'S OWN CARD. What this asks is "which of these", over a list too long to
 * read and short enough to search, which is the question the command palette answers on every
 * other surface in this app -- so it is the same dialog, the same search row, the same shelved
 * rows, and the same every-term filter rather than a fourth kind of chooser.
 *
 * THE SHELVES ARE THE CORPUS'S OWN. A starter is filed under the distribution that ships it and
 * then the directory it sits in, breadcrumbed the way the add-step menu breadcrumbs a block, so
 * a pack's `recipes` and the core corpus's are two shelves rather than one.
 *
 * WHAT IT NEEDS IS ON THE ROW. Choosing a starter that wants a connection nobody has created is
 * a legitimate thing to do -- the editor's panel then says what to create -- but it is not a
 * thing to discover afterwards, so how much of what it needs is here stands at the row's end, and
 * under the title on a phone.
 *
 * CHOOSING ONE READS IT IN PLACE. The palette stays open on the chosen row while the starter is
 * read, and a read that is refused is said in the palette, where the choice was made.
 *
 * THE COPY IS MADE HERE, AND IT IS `lib/starters`. What this answers with is a copy under its
 * own code with the `starter` tag off, which is what the Examples screen's own door hands over
 * too. What the document carries stays in it: an instance refuses a document that carries a
 * connection or a schema, and the dialog that refusal raises is where the shapes in it can
 * still be stored, so taking them out happens there rather than here.
 */
export function StarterPicker({
    open,
    onOpenChange,
    onChoose,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    /** The copy, and the code it was copied from. */
    onChoose: (document: string, starter: string) => void
}) {
    const corpus = useRead(readAllExamples)
    const instance = useRead(readHoldings)
    const holdings = useMemo<Holdings>(
        () => instance.value ?? { blocks: null, connections: null, schemas: null },
        [instance.value],
    )

    const starters = useMemo(() => (corpus.value ?? []).filter((row) => row.starter), [corpus.value])
    const byCode = useMemo(() => new Map(starters.map((row) => [row.code, row])), [starters])
    const groups = useMemo<PaletteGroup[]>(() => {
        function choose(starter: ExampleOut): Promise<void> {
            return readExample(starter.code).then(
                (detail) => {
                    onChoose(copyStarter(detail.source, detail.code), detail.code)
                },
                (error: unknown) => {
                    throw new Error(refusalLine(refusalOf(error)), { cause: error })
                },
            )
        }
        return shelveStarters(starters).map((shelf) => ({
            title: shelf.label,
            commands: shelf.rows.map((row) => starterCommand(row, holdings, () => choose(row))),
        }))
    }, [starters, holdings, onChoose])

    return (
        <CommandPalette
            open={open}
            onOpenChange={onOpenChange}
            groups={groups}
            filter={(command, query) => {
                const row = byCode.get(command.id)
                return row !== undefined && starterMatches(row, query) ? 1 : 0
            }}
            width="lg"
            description={LABELS.pipelines.starters.description}
            wrap
            words={{
                title: FROM_A_STARTER,
                placeholder: PICKER_PLACEHOLDER,
                empty: !corpus.read ? PICKER_READING : starters.length === 0 ? PICKER_NONE : PICKER_EMPTY,
                close: LABELS.palette.close,
                running: LABELS.pipelines.starters.reading,
                refused: LABELS.pipelines.starters.refused,
            }}
        />
    )
}

/** One starter: what it is called, the code a copy keeps, and what it needs of this instance. */
function starterCommand(
    starter: ExampleOut,
    holdings: Holdings,
    onSelect: () => Promise<void>,
): PaletteCommand {
    const heading = headingOf(starter)
    const items = requirementsOf(starter.requires, holdings)
    const summary = requirementsSummary(items)
    return {
        id: starter.code,
        label: heading.title,
        mono: !heading.named,
        code: heading.code ?? undefined,
        meta: summary ?? undefined,
        onSelect,
    }
}
