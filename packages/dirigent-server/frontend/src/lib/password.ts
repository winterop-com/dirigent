/**
 * Changing your own password, and what the refusals mean.
 *
 * TWO REFUSALS THAT ARE NOT THE SAME KIND OF THING. A new password shorter than this server
 * accepts, or the one already in use, is refused here without a request: there is nothing to
 * ask, and a round trip to be told what the form already knows is a round trip that carries
 * the old password over the wire for no reason. Everything else is the
 * server's -- above all "the current password is not correct", which only it can decide -- and
 * arrives as a problem document rendered in the words it wrote.
 *
 * A LOCAL REFUSAL WEARS THE SAME SHAPE AS A SERVER'S, so one renderer draws both and the form
 * has no second way of saying no.
 */

import { ApiError, apiSend, type Problem } from '@/lib/api'
import { MIN_PASSWORD_LENGTH } from '@/lib/users'

/** What the form holds. */
export interface PasswordForm {
    current: string
    next: string
}

/** The body `POST /auth/password` takes. `PasswordChangeRequest`. */
export interface PasswordChangeRequest {
    current_password: string
    new_password: string
}

/** Nothing typed yet. */
export const NO_PASSWORD: PasswordForm = { current: '', next: '' }

/** A refusal this form made, in the shape every refusal in this app takes. */
function refused(detail: string): Problem {
    return { status: 0, title: 'Not accepted', detail, problems: [], instance: null }
}

/** What the form itself refuses, or nothing when there is a request to make. */
export function formProblem(form: PasswordForm): Problem | null {
    if (form.current === '') return refused('Type the password this account signs in with now.')
    if (form.next.length < MIN_PASSWORD_LENGTH) {
        return refused(`A password must be at least ${String(MIN_PASSWORD_LENGTH)} characters.`)
    }
    if (form.next === form.current) return refused('The new password is the one already in use.')
    return null
}

/** The body, with the wire's own member names. */
export function passwordBody(form: PasswordForm): PasswordChangeRequest {
    return { current_password: form.current, new_password: form.next }
}

/** What a failed change leaves on screen: the server's problem document, or what arrived instead. */
export function refusalOf(error: unknown): Problem {
    if (error instanceof ApiError) return error.problem
    return refused('The server did not answer. The password has not been changed.')
}

/**
 * Change this account's password.
 *
 * A success is 204 and no body. Every other session of the account is revoked by the server;
 * the one that made the call survives, so nobody is signed out of the tab they did it in.
 */
export function changePassword(form: PasswordForm): Promise<void> {
    return apiSend<void>('/auth/password', 'POST', passwordBody(form))
}
