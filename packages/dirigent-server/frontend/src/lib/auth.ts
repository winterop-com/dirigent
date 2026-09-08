/**
 * Who this browser is, held once for the whole app.
 *
 * A COOKIE SESSION, NOT A TOKEN. `POST /auth/login` sets an http-only cookie, so this bundle
 * never holds a credential and there is nothing here to keep in storage. What is kept is the
 * answer to `GET /auth/me`: the account, and the role that decides whether the admin section
 * of the rail exists at all.
 *
 * THREE STATES, AND THE FIRST ONE IS NOT "SIGNED OUT". Before the first read answers, nobody
 * knows -- and a shell that guessed "signed out" would bounce a signed-in reader to the login
 * page on every reload. So `unknown` is its own state and the shell renders its frame and
 * nothing else until it resolves.
 *
 * ROLE GATING IS A COURTESY, NOT A CONTROL. The server refuses what an account may not do; the
 * rail hides it so nobody is offered a screen that will refuse them. Nothing here is a
 * security boundary.
 */

import { ApiError, apiJson, apiSend, type Problem } from '@/lib/api'
import { createStore } from '@/lib/store'

/** What an account may do. Mirrors `dirigent_client.enums.UserRole`. */
export type UserRole = 'admin' | 'operator' | 'viewer'

/** Whether the credential a request arrived on was a session or an automation token. */
export type TokenKind = 'api' | 'session'

/**
 * Who the caller is, as `GET /auth/me` answers.
 *
 * There is no display name on this document: the API carries one on `UserOut`, which only an
 * admin may list, so the rail and the status bar name an account by its username.
 */
export interface Identity {
    user_id: string
    username: string
    role: UserRole
    via: TokenKind | null
    token_name: string | null
}

/** Where the session stands, and what the last attempt to change it said. */
export interface AuthState {
    /** `unknown` until the first read answers; the shell waits on it. */
    status: 'unknown' | 'signed-in' | 'signed-out'
    identity: Identity | null
    /** The refusal from the last sign-in attempt, which is what the login page states. */
    problem: Problem | null
    /** True while a sign-in is in flight, so the form can refuse a second submit. */
    working: boolean
}

const initial: AuthState = { status: 'unknown', identity: null, problem: null, working: false }

export const authStore = createStore<AuthState>(initial)

/** Whether this account may reach the admin section. */
export function isAdmin(state: AuthState): boolean {
    return state.identity?.role === 'admin'
}

/**
 * Ask the server who this browser is.
 *
 * A 401 is the answer "nobody", not a failure: it is how a browser with no cookie, or with an
 * expired one, is told where it stands. Anything else leaves the state as it was, because a
 * server that is briefly unreachable has not signed anybody out.
 */
export async function refreshIdentity(): Promise<void> {
    try {
        const identity = await apiJson<Identity>('/auth/me')
        authStore.set({ status: 'signed-in', identity, problem: null, working: false })
    } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
            authStore.set({ status: 'signed-out', identity: null, problem: null, working: false })
            return
        }
        throw error
    }
}

/**
 * Sign in, and hold whatever the server said about the attempt.
 *
 * The refusal is kept on the store rather than thrown, because the login form is the only
 * caller and a wrong password is not an exceptional condition there -- it is the sentence
 * under the field. The server's own wording is used: it is the one that knows whether this
 * was a bad password or a rate limit.
 */
export async function signIn(username: string, password: string): Promise<boolean> {
    authStore.update((current) => ({ ...current, problem: null, working: true }))
    try {
        const identity = await apiSend<Identity>('/auth/login', 'POST', { username, password })
        authStore.set({ status: 'signed-in', identity, problem: null, working: false })
        return true
    } catch (error) {
        const problem = error instanceof ApiError ? error.problem : null
        authStore.set({ status: 'signed-out', identity: null, problem, working: false })
        return false
    }
}

/**
 * Sign out, whatever the server makes of it.
 *
 * The local state is cleared even when the call fails: the reader asked to end the session, and
 * leaving them looking at a signed-in shell because the network blinked is the wrong answer. A
 * cookie the server still honours is picked up again by the next `refreshIdentity`.
 */
export async function signOut(): Promise<void> {
    try {
        await apiSend<void>('/auth/logout', 'POST', {})
    } finally {
        authStore.set({ status: 'signed-out', identity: null, problem: null, working: false })
    }
}
