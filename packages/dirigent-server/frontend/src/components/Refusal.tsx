import { toast } from 'sonner'

import type { Problem } from '@/lib/api'
import { refusalLine, refusalLines, refusalOf } from '@/lib/refusal'

/**
 * A refusal inside something already on screen: a dialog, a form, a panel.
 *
 * `PageState` is the card a whole screen becomes when its read was refused. This is the same
 * problem document beside the thing that was refused, which is where a form's refusal belongs.
 *
 * IT IS NOT HEADED BY THE STATUS PHRASE. `Problem.title` is what the status says rather than
 * what happened, so every refusal a dialog can make would be headed "Unprocessable Content".
 * What the server wrote for a person to act on leads instead, and `lib/refusal` is what decides
 * whether the failures under it add anything to that sentence or repeat it.
 *
 * It is an `alert`, because a refusal that appears where somebody is typing is not read unless
 * it is announced.
 */
export function Refusal({ problem }: { problem: Problem }) {
    const lines = refusalLines(problem)
    return (
        <div className="border-critical/40 space-y-1 rounded-md border p-2" role="alert">
            {lines.detail !== null && <p className="text-critical text-sm break-words">{lines.detail}</p>}
            {lines.problems.length > 0 && (
                <ul className="text-critical list-disc space-y-0.5 pl-4 text-xs">
                    {lines.problems.map((one) => (
                        <li key={one} className="font-mono break-all">
                            {one}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}

/**
 * Say a refusal where the thing refused has nowhere to put one.
 *
 * A row's button and a panel's verb are pressed against a listing, and there is no card beside
 * either -- so the refusal is a toast, which is the one place in this app that says something
 * about a request nothing on screen is waiting for.
 */
export function sayRefusal(error: unknown): void {
    toast.error(refusalLine(refusalOf(error)))
}
