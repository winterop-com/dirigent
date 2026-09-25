import { createContext, use, type ReactNode } from 'react'

/**
 * What the listing a cell is being drawn in measured about itself.
 *
 * A cell that decides what fits has to know what it is fitting into, and the answer is the
 * listing rather than the cell: a cell as wide as what is in it would answer with the width its
 * own content already took. `ListTable` measures itself once and every row reads it here.
 *
 * THE FORM IS THE LISTING'S ANSWER, NOT THE WINDOW'S. A cell drawn differently on a card asks
 * `useListCards`, because the listing beside an open panel is drawing cards while the window
 * around it is as wide as it ever was.
 *
 * Zero is a listing nothing has measured yet, which a cell reads as "no bound to work to".
 */
const ListWidth = createContext(0)

const ListCards = createContext(false)

export function ListFormProvider({
    width,
    cards,
    children,
}: {
    width: number
    cards: boolean
    children: ReactNode
}) {
    return (
        <ListWidth value={width}>
            <ListCards value={cards}>{children}</ListCards>
        </ListWidth>
    )
}

export function useListWidth(): number {
    return use(ListWidth)
}

export function useListCards(): boolean {
    return use(ListCards)
}
