import { useRef } from 'react'
import { toast } from 'sonner'

import { refusalOf, refusalLine } from '@/lib/refusal'

/**
 * A busy confirm the reader may let go with Stop waiting, after which the dialog has closed and a
 * refusal it would have drawn is said as a toast instead.
 *
 * `begin` is called as the work starts, `onStopWaiting` is the confirm's own, and `refused` takes
 * the error: it answers the problem to draw while the dialog is still waiting, and null once the
 * toast has said it.
 */
export function useLetGo() {
    const away = useRef(false)
    return {
        begin: () => {
            away.current = false
        },
        onStopWaiting: () => {
            away.current = true
        },
        refused: (error: unknown) => {
            const problem = refusalOf(error)
            if (!away.current) return problem
            toast.error(refusalLine(problem))
            return null
        },
    }
}
