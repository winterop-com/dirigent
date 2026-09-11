import { useMemo, useState } from 'react'

import {
    Command,
    CommandDialog,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from '@/components/ui/command'
import { useRead } from '@/hooks/use-read'
import {
    missingCount,
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
import { sayRefusal } from '@/components/Refusal'
import { instantiate } from '@/lib/starters'
import { cn } from '@/lib/utils'

export const FROM_A_STARTER = 'From a starter'

export const PICKER_PLACEHOLDER = 'Search the starters'

export const PICKER_EMPTY = 'No starter answers to that'

export const PICKER_READING = 'Reading the corpus'

export const PICKER_NONE = 'No starters installed — plugins contribute them.'

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
 * thing to discover afterwards, so how much of what it needs is here stands beside the title.
 *
 * THE COPY IS MADE HERE, AND IT IS `lib/starters`. What this answers with is the document text
 * a `dg pipeline new` of the same starter would have written, so the caller opens an editor on
 * it and knows nothing about the rewrite -- there is one copy rule and both surfaces use it.
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
    const [query, setQuery] = useState('')

    const corpus = useRead(readAllExamples)
    const instance = useRead(readHoldings)
    const holdings = useMemo<Holdings>(
        () => instance.value ?? { blocks: null, connections: null, schemas: null },
        [instance.value],
    )

    const starters = useMemo(() => (corpus.value ?? []).filter((row) => row.starter), [corpus.value])
    const shelves = useMemo(
        () => shelveStarters(starters.filter((row) => starterMatches(row, query))),
        [query, starters],
    )

    function choose(starter: ExampleOut): void {
        void readExample(starter.code).then(
            (detail) => {
                onOpenChange(false)
                setQuery('')
                onChoose(instantiate(detail.source, detail.code), detail.code)
            },
            (error: unknown) => {
                sayRefusal(error)
            },
        )
    }

    return (
        <CommandDialog
            open={open}
            onOpenChange={(next) => {
                onOpenChange(next)
                if (!next) setQuery('')
            }}
            title={FROM_A_STARTER}
            description="Copy a shipped document into the editor, under a code of your own"
            className="top-[15vh] w-full p-0 shadow-2xl sm:max-w-[768px]"
        >
            <Command shouldFilter={false} label={FROM_A_STARTER} className="dg-palette p-0">
                <CommandInput
                    placeholder={PICKER_PLACEHOLDER}
                    value={query}
                    onValueChange={setQuery}
                    autoFocus
                    className="text-base"
                />
                <CommandList className="max-h-[26rem] p-2">
                    <CommandEmpty>
                        {!corpus.read ? PICKER_READING : starters.length === 0 ? PICKER_NONE : PICKER_EMPTY}
                    </CommandEmpty>
                    {shelves.map((shelf) => (
                        <CommandGroup key={shelf.label} heading={shelf.label} className="p-0 pb-1">
                            {shelf.rows.map((row) => (
                                <Row
                                    key={row.code}
                                    starter={row}
                                    holdings={holdings}
                                    onChoose={() => {
                                        choose(row)
                                    }}
                                />
                            ))}
                        </CommandGroup>
                    ))}
                </CommandList>
            </Command>
        </CommandDialog>
    )
}

/** One starter: what it is called, the code a copy keeps, and what it needs of this instance. */
function Row({
    starter,
    holdings,
    onChoose,
}: {
    starter: ExampleOut
    holdings: Holdings
    onChoose: () => void
}) {
    const heading = headingOf(starter)
    const items = requirementsOf(starter.requires, holdings)
    const summary = requirementsSummary(items)
    const missing = missingCount(items)

    return (
        <CommandItem value={starter.code} onSelect={onChoose} className="h-11 gap-3 rounded-md px-2">
            <span className={cn('shrink-0 truncate text-sm', !heading.named && 'font-mono')}>
                {heading.title}
            </span>
            {/* The code takes the slack, so what a row says about its requirements is in one
                column down the list rather than wherever that row's code happened to end. */}
            {heading.code !== null && (
                <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
                    {heading.code}
                </span>
            )}
            {summary !== null && (
                <span
                    className={cn(
                        'shrink-0 text-xs',
                        missing === 0 ? 'text-muted-foreground' : 'text-critical',
                    )}
                >
                    {summary}
                </span>
            )}
        </CommandItem>
    )
}
