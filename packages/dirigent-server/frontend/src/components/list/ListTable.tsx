import { Fragment, useEffect, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react'

import { ListWidthProvider } from '@/components/list/ListWidth'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { useElementWidth } from '@/hooks/use-element-width'
import { useNarrowTable } from '@/hooks/use-small-screen'
import { PAGE, rowsRead } from '@/lib/paging'
import { cn } from '@/lib/utils'

/** One column: what its heading says, and what one row puts in it. */
export interface ListChrome {
    /** Draw the column header row. A grouped listing names its groups instead. */
    header?: boolean
    /** Draw the count footer. A grouped listing counts once, outside its groups. */
    footer?: boolean
}

export interface Column<T> {
    /** Stable across renders, so React can key on it and a test can name it. */
    id: string
    header: ReactNode
    /** Classes carried by this column's heading and by every cell under it. */
    className?: string
    cell: (row: T) => ReactNode
    /**
     * What this column is called on a card, where the header row is not drawn.
     *
     * The header is the label wherever it is a word; a column headed by nothing says nothing
     * on the card either.
     */
    cardLabel?: string
}

/** How far ahead of the fold the next page is asked for. */
const REACH = '300px'

/** What a column is called on a card: its header where that is a word, and nothing else. */
function labelOf<T>(column: Column<T>): string | null {
    if (column.cardLabel !== undefined) return column.cardLabel
    return typeof column.header === 'string' && column.header !== '' ? column.header : null
}

/** Whether a cell has anything in it, which is what keeps an empty fact off a card. */
function said(cell: ReactNode): boolean {
    return cell !== null && cell !== undefined && cell !== false && cell !== ''
}

/**
 * The table every listing screen in this app is drawn as.
 *
 * ONE IMPLEMENTATION, NOT ONE PER SCREEN. A screen decides its columns and what each cell says;
 * the heading row, the striping, how the next page is reached for and what the foot states are
 * the same on every listing, and live here so they cannot drift apart.
 *
 * THE FOOT COUNTS WHAT IS LOADED, NEVER WHAT EXISTS. This API pages by cursor and answers no
 * total, so there is no last page to jump to and no number of pages to state. What is honest is
 * how many rows have been read and whether there are more, and that is what the foot says.
 *
 * The next page is asked for when the row that would load it comes into view, and the button is
 * still a button: an observer is how a pointer reaches the end of a list, and the button is how
 * a keyboard does.
 *
 * A ROW THAT OPENS SOMETHING IS REACHABLE FROM A KEYBOARD. Where a screen passes `onSelect`,
 * the row answers a click and answers Enter and Space, and says which row is open through
 * `aria-selected` -- because a row that only a pointer can open is a row some people cannot.
 */
export function ListTable<T>({
    chrome,
    fixed,
    columns,
    rows,
    rowKey,
    rowClassName,
    reading,
    next,
    onMore,
    noun,
    onSelect,
    selected,
}: {
    /** Which chrome to draw. A grouped listing turns the header and footer off. */
    chrome?: ListChrome
    /**
     * Honour the columns' declared widths exactly (`table-layout: fixed`).
     *
     * Auto layout treats a width class as a minimum and sizes to content, so the same
     * columns land a few pixels apart between two tables on one screen; a page that stacks
     * sections of one shape says fixed and they align.
     */
    fixed?: boolean
    columns: readonly Column<T>[]
    rows: readonly T[]
    rowKey: (row: T) => string
    /** Extra classes for one row, which is how a listing dims what is no longer live. */
    rowClassName?: (row: T) => string | undefined
    reading: boolean
    /** The cursor the next page continues from, or null at the end of the listing. */
    next: string | null
    onMore: () => void
    /** What one row is, in the plural, for the sentence along the foot. */
    noun: string
    /** What choosing a row does, on a screen where a row opens something beside the table. */
    onSelect?: (row: T) => void
    /** Which row is open, so the table can say so. */
    selected?: (row: T) => boolean
}) {
    // A callback ref rather than a held one: the row carrying it is only rendered while there is
    // a next page, so its arrival and departure are what start and stop the observer.
    const [sentinel, setSentinel] = useState<HTMLDivElement | null>(null)

    useEffect(() => {
        if (sentinel === null) return
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries.some((entry) => entry.isIntersecting)) onMore()
            },
            { rootMargin: REACH },
        )
        observer.observe(sentinel)
        return () => {
            observer.disconnect()
        }
    }, [onMore, sentinel])

    // What choosing a row does, which a table row and a card both answer to. A row only a
    // pointer can open is a row some people cannot.
    const chooses = (row: T) =>
        onSelect === undefined
            ? {}
            : {
                  tabIndex: 0,
                  'aria-selected': selected?.(row),
                  onClick: () => {
                      onSelect(row)
                  },
                  onKeyDown: (event: ReactKeyboardEvent<HTMLElement>) => {
                      if (event.key !== 'Enter' && event.key !== ' ') return
                      if (event.target !== event.currentTarget) return
                      event.preventDefault()
                      onSelect(row)
                  },
              }

    const head = columns[0]
    const facts = columns.slice(1)
    const cards = useNarrowTable()

    // Measured once for the whole listing: a cell that has to decide what fits reads it from
    // here rather than measuring itself, which would be a read per row on every resize.
    const [box, setBox] = useState<HTMLDivElement | null>(null)
    const width = useElementWidth(box)

    return (
        <ListWidthProvider width={width}>
        <div className="border-border-strong bg-card flex min-h-0 flex-col overflow-hidden rounded-md border">
            {/* The container the columns' shares are taken of, and the box that is measured:
                the table's own width, inside the card's border rather than across it. */}
            <div ref={setBox} className="list-scroll @container min-h-0 flex-1 overflow-auto">
                {/* THE SAME ROWS AS CARDS BELOW `lg`. A table of six columns in the 500px the
                    content column has beside the rail is either a horizontal scroll or one
                    cell drawn over another, so the first column becomes the card's head and
                    every other one a labelled fact under it -- labelled by the header that
                    names it in the table. */}
                {cards && head !== undefined ? (
                    <ul className="divide-border divide-y">
                        {rows.map((row) => (
                            <li
                                key={rowKey(row)}
                                {...chooses(row)}
                                className={cn(
                                    'row-hover flex min-h-10 flex-col justify-center gap-2 px-3 py-3',
                                    selected?.(row) === true && 'bg-accent/70',
                                    onSelect !== undefined && 'cursor-pointer',
                                    rowClassName?.(row),
                                )}
                            >
                                <div className="min-w-0">{head.cell(row)}</div>
                                {facts.some((column) => said(column.cell(row))) && (
                                    <dl className="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
                                        {facts.map((column) => {
                                            const cell = column.cell(row)
                                            if (!said(cell)) return null
                                            const label = labelOf(column)
                                            return (
                                                <Fragment key={column.id}>
                                                    <dt className="text-faint">{label}</dt>
                                                    <dd className="min-w-0">{cell}</dd>
                                                </Fragment>
                                            )
                                        })}
                                    </dl>
                                )}
                            </li>
                        ))}
                    </ul>
                ) : (
                <Table containerClassName="overflow-x-visible" className={cn(fixed && 'table-fixed')}>
                {chrome?.header !== false && (
                <TableHeader className="bg-card sticky top-0 z-10">
                    <TableRow className="border-border-strong hover:bg-transparent">
                        {columns.map((column) => (
                            <TableHead
                                key={column.id}
                                className={cn('text-muted-foreground px-3 text-xs font-medium', column.className)}
                            >
                                {column.header}
                            </TableHead>
                        ))}
                    </TableRow>
                </TableHeader>
                )}
                <TableBody>
                    {rows.map((row) => (
                        <TableRow
                            key={rowKey(row)}
                            className={cn(
                                'row-hover border-border',
                                // The stripe steps aside for the selection: `even:` carries a
                                // pseudo-class, so left in place it would outrank the tint and
                                // every even row would look unselected.
                                selected?.(row) === true
                                    ? 'bg-accent/70 even:bg-accent/70 hover:bg-accent/70'
                                    : cn('even:bg-secondary/30', onSelect !== undefined && 'hover:bg-accent/60'),
                                onSelect !== undefined && 'cursor-pointer',
                                rowClassName?.(row),
                            )}
                            {...chooses(row)}
                        >
                            {columns.map((column) => (
                                <TableCell key={column.id} className={cn('px-3 py-2', column.className)}>
                                    {column.cell(row)}
                                </TableCell>
                            ))}
                        </TableRow>
                    ))}
                </TableBody>
                </Table>
                )}

                {next !== null && (
                    <div ref={setSentinel} className="border-border border-t p-1.5">
                    <Button
                        variant="ghost"
                        size="sm"
                        className="text-muted-foreground w-full"
                        onClick={onMore}
                        disabled={reading}
                    >
                            {reading ? 'Reading' : `Load ${String(PAGE)} more`}
                        </Button>
                    </div>
                )}
            </div>

            {chrome?.footer !== false && (
                <div className="border-border text-faint shrink-0 border-t px-3 py-2 text-xs">
                    {rowsRead(rows.length, noun, next !== null)}
                </div>
            )}
        </div>
        </ListWidthProvider>
    )
}
