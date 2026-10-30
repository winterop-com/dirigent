/**
 * The decisions the design-system components in `components/ds` make, as pure functions.
 *
 * A component draws; what it says, when a word appears beside a dot, and what a key does to a
 * search box are decided here, where a Node test can hold them.
 */

/** What a dot or a notice says about something that is not a run: how it is, in one hue. */
export type Tone = 'good' | 'critical' | 'warning' | 'info' | 'quiet' | 'unknown'

/** The one map from a tone to the token it is filled with. `unknown` is drawn hollow. */
export const TONE_FILL: Readonly<Record<Tone, string>> = {
    good: 'var(--good)',
    critical: 'var(--critical)',
    warning: 'var(--warning)',
    info: 'var(--info)',
    quiet: 'var(--faint)',
    unknown: 'var(--faint)',
}

/** The tones that are news: a dot in one of these says its word beside it, not only on hover. */
export const NEWS_TONES: ReadonlySet<Tone> = new Set(['critical', 'unknown'])

/** The run and attempt states that are news, read the same way. */
export const NEWS_STATUSES: ReadonlySet<string> = new Set(['failed', 'completed_with_errors'])

/** When a dot spells its word: only when it is news, always, or never. */
export type Say = 'news' | 'always' | 'never'

/**
 * Whether a dot draws its word beside it.
 *
 * A green dot alone says connected; a word appears where the state is news. The word is the
 * dot's accessible name and its tooltip either way.
 */
export function saysWord(news: boolean, say: Say = 'news'): boolean {
    if (say === 'always') return true
    if (say === 'never') return false
    return news
}

/** Whether a tone or a status is news. */
export function isNews(dot: { tone: Tone } | { status: string }): boolean {
    return 'tone' in dot ? NEWS_TONES.has(dot.tone) : NEWS_STATUSES.has(dot.status)
}

/**
 * What an icon button's tooltip says.
 *
 * A shut button says why it is shut, which is the one fact its own name cannot give; otherwise
 * the tooltip, or the name itself when nothing longer was given.
 */
export function iconButtonTip({
    label,
    tooltip,
    why,
}: {
    label: string
    tooltip?: string
    why?: string
}): string {
    if (why !== undefined && why !== '') return why
    return tooltip ?? label
}

/** Whether a search box offers its clear button: only once there is something to clear. */
export function clearShown(value: string): boolean {
    return value !== ''
}

/** What Escape does in a search box: empties a box with text in it, leaves an empty one. */
export function escapeFrom(value: string): 'clear' | 'leave' {
    return value === '' ? 'leave' : 'clear'
}

/** The widths a dialog may take, and nothing between them. */
export const DIALOG_WIDTHS = {
    sm: 'sm:max-w-sm',
    md: 'sm:max-w-lg',
    lg: 'sm:max-w-2xl',
    xl: 'sm:max-w-4xl',
} as const

export type DialogWidth = keyof typeof DIALOG_WIDTHS
