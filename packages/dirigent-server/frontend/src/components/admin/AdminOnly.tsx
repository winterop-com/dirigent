import type { ReactNode } from 'react'

import { PageState } from '@/components/PageState'
import { useStore } from '@/hooks/use-store'
import type { Problem } from '@/lib/api'
import { authStore, isAdmin } from '@/lib/auth'
import { LABELS } from '@/lib/labels'

/**
 * What a reader who is not an admin is told, in the shape every refusal in this app takes.
 *
 * No request was made -- the reader typed an address the rail does not offer them -- so this
 * app states the refusal the server would have made, in the words the server states it in and
 * under its code. A screen that invented its own sentence had the product refusing one thing
 * two ways, depending only on whether anybody had pressed anything yet.
 */
export const ADMIN_REFUSAL: Problem = {
    status: 403,
    title: LABELS.refusal.admin_only,
    code: 'server.forbidden',
    params: {},
    detail: LABELS.refusal.shut,
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
