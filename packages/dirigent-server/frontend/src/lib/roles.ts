/**
 * What a role may do, said once for every control that would do it.
 *
 * TWO GATES, BECAUSE THE API HAS TWO. `require_operator` stands in front of applying, running
 * and scheduling; `require_admin` stands in front of connections, schemas, accounts and tokens.
 * A control asks which gate its request is behind and gets back the sentence to wear, so what a
 * viewer may not do is decided here rather than spelled out per screen.
 *
 * THIS IS A COURTESY, NOT A CONTROL. The server refuses what an account may not do; a shut
 * button means nobody presses one to be told off. A role this bundle has not read yet shuts
 * nothing, or every screen would open disabled for a frame.
 */

import type { UserRole } from '@/lib/auth'

/** Which of the API's two role gates a request is behind. */
export type Gate = 'operator' | 'admin'

/** Whether this role passes a gate. An unread identity passes, and the server decides. */
export function passes(role: UserRole | null, gate: Gate): boolean {
    if (role === null || role === 'admin') return true
    return gate === 'operator' && role === 'operator'
}

/**
 * Why a control behind this gate is shut for this role, or nothing when it is not.
 *
 * It says that the account cannot, and not what any other role could: a shut button is not
 * where somebody is taught the permission model, and the server's own refusal says as little.
 */
export function whyShut(role: UserRole | null, gate: Gate): string | undefined {
    if (passes(role, gate)) return undefined
    return `Not available to ${role === 'operator' ? 'an operator' : 'a viewer'}.`
}

/** The first sentence that shuts a control, so a role and a form's own state read as one. */
export function firstShut(...reasons: (string | undefined)[]): string | undefined {
    return reasons.find((reason) => reason !== undefined)
}
