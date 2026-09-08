import { createContext, use, type ReactNode } from 'react'

/**
 * How wide the listing a cell is being drawn in is.
 *
 * A cell that decides what fits has to know what it is fitting into, and the answer is the
 * table rather than the cell: a cell as wide as what is in it would answer with the width its
 * own content already took. `ListTable` measures itself once and every row reads it here.
 *
 * Zero is a listing nothing has measured yet, and a cell reads that as "no bound to work to".
 */
const ListWidth = createContext(0)

export function ListWidthProvider({ width, children }: { width: number; children: ReactNode }) {
    return <ListWidth value={width}>{children}</ListWidth>
}

export function useListWidth(): number {
    return use(ListWidth)
}
