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
import { LABELS } from '@/lib/labels'
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
    expires_at: string | null
}

/** How short a password this server refuses. `MIN_PASSWORD_LENGTH` in the server's security module. */
export const MIN_PASSWORD_LENGTH = 8

/** The roles an account can hold, in the order a menu offers them. */
export const USER_ROLES: readonly UserRole[] = ['admin', 'operator', 'viewer']

/** What each role may do, in one line, which is what a menu row says under its name. */
export const ROLE_HINTS: Record<UserRole, string> = LABELS.users.role_hint

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

/** The most one request answers, which is what a count over the whole listing asks for. */
const WHOLE_PAGE = 500

/** Read as many automation tokens as one request answers, oldest first. Sessions are never listed. */
export function readTokenCensus(): Promise<Page<TokenOut>> {
    return apiJson<Page<TokenOut>>(tokensPath(null, WHOLE_PAGE))
}

/** Read one page of the automation tokens one account holds, oldest first. */
export function readAccountTokens(username: string, after: string | null): Promise<Page<TokenOut>> {
    const query = new URLSearchParams({ limit: String(PAGE) })
    if (after !== null) query.set('after', after)
    return apiJson<Page<TokenOut>>(`/users/${encodeURIComponent(username)}/tokens?${query.toString()}`)
}

/** Whether a token can still authenticate at this moment. */
export function isLive(token: Pick<TokenOut, 'revoked_at' | 'expires_at'>, now: number): boolean {
    if (token.revoked_at !== null) return false
    return token.expires_at === null || Date.parse(token.expires_at) > now
}

/** The names two or more live tokens of one account share, which is when a prefix is worth drawing. */
export function sharedNames(
    tokens: readonly Pick<TokenOut, 'name' | 'revoked_at' | 'expires_at'>[],
    now: number,
): ReadonlySet<string> {
    const seen = new Set<string>()
    const shared = new Set<string>()
    for (const token of tokens) {
        if (!isLive(token, now)) continue
        if (seen.has(token.name)) shared.add(token.name)
        seen.add(token.name)
    }
    return shared
}

/** How many tokens a revoke by this name takes: every one not yet revoked, expired or not. */
export function revokedTogether(
    tokens: readonly Pick<TokenOut, 'name' | 'revoked_at'>[],
    name: string,
): number {
    return tokens.filter((token) => token.name === name && token.revoked_at === null).length
}

/**
 * How many live tokens each account holds, or null where the read did not reach the end.
 *
 * A number off part of the listing is not a count, so a listing longer than one request says
 * nothing rather than something too low.
 */
export function tokenCounts(
    page: Pick<Page<TokenOut>, 'items' | 'next'>,
    now: number,
): ReadonlyMap<string, number> | null {
    if (page.next !== null) return null
    const counts = new Map<string, number>()
    for (const token of page.items) {
        if (isLive(token, now)) counts.set(token.username, (counts.get(token.username) ?? 0) + 1)
    }
    return counts
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
