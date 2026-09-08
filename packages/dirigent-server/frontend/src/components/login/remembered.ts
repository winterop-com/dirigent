/**
 * The username this browser signed in as last, so a returning reader types a password and
 * nothing else.
 *
 * A per-viewer convenience and never a credential: no password is kept, and the session itself
 * is an http-only cookie this bundle cannot read. Storage that refuses to be read or written --
 * a private window, a browser with site data denied -- is the same answer as storage that holds
 * nothing.
 */

/** Where the last username is kept. */
export const USERNAME_STORAGE_KEY = 'dirigent.username'

/** The username this browser last signed in as, or the empty string. */
export function rememberedUsername(): string {
    try {
        return localStorage.getItem(USERNAME_STORAGE_KEY) ?? ''
    } catch {
        return ''
    }
}

/** Keep a username for the next visit. A blank one forgets what was held. */
export function rememberUsername(username: string): void {
    try {
        if (username === '') localStorage.removeItem(USERNAME_STORAGE_KEY)
        else localStorage.setItem(USERNAME_STORAGE_KEY, username)
    } catch {
        // Storage denied: the form works, and only the prefill on the next visit is lost.
    }
}
