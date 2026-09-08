/**
 * Local accounts and the tokens automation authenticates with.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface here mirrors a pydantic model in
 * `dirigent_client.schemas.auth` member for member.
 *
 * THE LAST ADMIN IS THE SERVER'S RULE, NOT THIS APP'S. Demoting or deactivating the only active
 * admin is refused with 409 and a sentence naming the account, and the screen renders that
 * sentence rather than deciding for itself which buttons to hide. A guard drawn client-side
 * would have to reimplement "which accounts are admins, and which are active" over whichever
 * page of the listing happens to be loaded, and would be wrong the moment somebody else made a
 * change in another tab.
 */

import { apiJson, apiSend, type Page } from '@/lib/api'
import type { UserRole } from '@/lib/auth'
import { headingOf, type Heading } from '@/lib/identity'
import { PAGE } from '@/lib/paging'

/** One local account. `UserOut`. */
export interface UserOut {
    id: string
    username: string
    /** What to call this account on screen. The username is what it signs in as. */
    name: string | null
    email: string | null
    role: UserRole
    active: boolean
    last_login_at: string | null
    created_at: string
}

/** A new account, as `POST /users` takes one. `UserIn`. */
export interface UserIn {
    username: string
    password: string
    name?: string | null
    email?: string | null
    role: UserRole
}

/**
 * What a PATCH may change, which is the name, the email and the role. `UserUpdate`.
 *
 * A field left out is left alone; a field sent as null is cleared.
 */
export interface UserUpdate {
    name?: string | null
    email?: string | null
    role?: UserRole
}

/** One automation token, as the listing carries it. `TokenOut`. */
export interface TokenOut {
    id: string
    name: string
    /** The account this token authenticates as. */
    username: string
    /** The head of the secret, which is how a token is recognised in a log without holding one. */
    prefix: string
    created_at: string
    last_used_at: string | null
    expires_at: string | null
    revoked_at: string | null
}

/** A minted token: the only time the secret itself is ever answered. `IssuedTokenOut`. */
export interface IssuedTokenOut {
    id: string
    name: string
    /** The account this token authenticates as. */
    username: string
    prefix: string
    /** The secret, in full, once. It is not stored and cannot be read again. */
    token: string
}

/** How short a password this server refuses. `MIN_PASSWORD_LENGTH` in the server's security module. */
export const MIN_PASSWORD_LENGTH = 8

/** The roles an account can hold, in the order a menu offers them. */
export const USER_ROLES: readonly UserRole[] = ['admin', 'operator', 'viewer']

/** What each role may do, in one line, which is what a menu row says under its name. */
export const ROLE_HINTS: Record<UserRole, string> = {
    admin: 'Everything, including accounts, tokens and connections.',
    operator: 'Define, run and observe pipelines.',
    viewer: 'Read what this instance holds, and change nothing.',
}

/** Where one page of the users listing is read from. */
export function usersPath(after: string | null, limit: number = PAGE): string {
    const query = new URLSearchParams({ limit: String(limit) })
    if (after !== null) query.set('after', after)
    return `/users?${query.toString()}`
}

/** Read one page of accounts, in username order. */
export function readUsers(after: string | null): Promise<Page<UserOut>> {
    return apiJson<Page<UserOut>>(usersPath(after))
}

/** Make an account. */
export function createUser(user: UserIn): Promise<UserOut> {
    return apiSend<UserOut>('/users', 'POST', user)
}

/** Change an account's name, its email, its role, or any of them together. */
export function updateUser(username: string, change: UserUpdate): Promise<UserOut> {
    return apiSend<UserOut>(`/users/${encodeURIComponent(username)}`, 'PATCH', change)
}

/**
 * Turn an account off, or back on.
 *
 * Deactivating the only active admin is refused with 409, and the sentence the server refuses
 * with names the account. Activating never is.
 */
export function setUserActive(username: string, active: boolean): Promise<UserOut> {
    const verb = active ? '$activate' : '$deactivate'
    return apiJson<UserOut>(`/users/${encodeURIComponent(username)}/${verb}`, { method: 'POST' })
}

/**
 * Set an account's password without presenting the old one.
 *
 * Every session that account holds ends; the tokens it holds keep working.
 */
export function resetPassword(username: string, password: string): Promise<void> {
    return apiSend<void>(`/users/${encodeURIComponent(username)}/$reset-password`, 'POST', { password })
}

/** Where one page of the tokens listing is read from. */
export function tokensPath(after: string | null, limit: number = PAGE): string {
    const query = new URLSearchParams({ limit: String(limit) })
    if (after !== null) query.set('after', after)
    return `/tokens?${query.toString()}`
}

/** Read one page of live automation tokens, oldest first. Sessions are never listed. */
export function readTokens(after: string | null): Promise<Page<TokenOut>> {
    return apiJson<Page<TokenOut>>(tokensPath(after))
}

/** Mint a token. The secret it answers with is the only copy there will ever be. */
export function createToken(name: string): Promise<IssuedTokenOut> {
    return apiSend<IssuedTokenOut>('/tokens', 'POST', { name })
}

/** Mint a token for another account. The secret it answers with is the only copy there will ever be. */
export function createTokenFor(username: string, name: string): Promise<IssuedTokenOut> {
    return apiSend<IssuedTokenOut>(`/users/${encodeURIComponent(username)}/tokens`, 'POST', { name })
}

/** Revoke one account's live tokens of this name. */
export function revokeToken(username: string, name: string): Promise<void> {
    const path = `/users/${encodeURIComponent(username)}/tokens/${encodeURIComponent(name)}`
    return apiJson<void>(path, { method: 'DELETE' })
}

/**
 * How an account is headed on screen.
 *
 * THE USERNAME IS THE ACCOUNT'S CODE. It is what a session signs in as, what a PATCH addresses,
 * and what appears in a path -- so it plays the part `code` plays for everything else this API
 * answers, and the same `lib/identity` decides the title over it.
 */
export function accountHeading(user: Pick<UserOut, 'username' | 'name'>): Heading {
    return headingOf({ code: user.username, name: user.name })
}
