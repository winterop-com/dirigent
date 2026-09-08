import type { ReactNode } from 'react'

import { PageState } from '@/components/PageState'
import { useStore } from '@/hooks/use-store'
import type { Problem } from '@/lib/api'
import { authStore, isAdmin } from '@/lib/auth'

/**
 * What a reader who is not an admin is told, in the shape every refusal in this app takes.
 *
 * The sentence is this app's rather than the server's, because no request was made: the reader
 * typed an address the rail does not offer them, and the honest answer is what the screen is
 * for and who it is for, not a 403 nobody asked for.
 */
export const ADMIN_REFUSAL: Problem = {
    status: 403,
    title: 'Forbidden',
    detail:
        "This screen is an admin's. Operators may define, run and observe pipelines; managing " +
        "accounts, tokens and connections is an admin's.",
    problems: [],
    instance: null,
}

/**
 * The role gate, drawn where the screen would be.
 *
 * THE RAIL HIDING THE SECTION IS NOT A GUARD. It is a courtesy, and an address can be typed, so
 * every admin screen states its own refusal rather than mounting and firing a page of reads the
 * server will refuse one at a time. Nothing here is a security boundary either: the server
 * refuses what an account may not do, and this only decides what is worth putting on screen.
 */
export function AdminOnly({ children }: { children: ReactNode }) {
    const auth = useStore(authStore)
    if (!isAdmin(auth)) {
        return (
            <PageState loading={false} problem={ADMIN_REFUSAL} empty={false}>
                {null}
            </PageState>
        )
    }
    return <>{children}</>
}
