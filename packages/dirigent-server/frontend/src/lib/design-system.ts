/**
 * The decisions the design-system components make, as pure functions, and the words sokkel-ui's
 * components say here.
 *
 * A component draws; what it says and when a word appears beside a dot are decided here, where a
 * Node test can hold them.
 */

import type { CopyButtonWords } from '@winterop-com/sokkel-ui/CopyButton'
import type { DialogShellWords } from '@winterop-com/sokkel-ui/DialogShell'
import type { SearchFieldWords } from '@winterop-com/sokkel-ui/SearchField'
import type { SecretRevealWords } from '@winterop-com/sokkel-ui/SecretReveal'
import type { SplitButtonWords } from '@winterop-com/sokkel-ui/SplitButton'
import type { TextLinkWords } from '@winterop-com/sokkel-ui/TextLink'

import { LABELS } from '@/lib/labels'

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

/** What a copy button is called before a press, `copy`, and for a moment after it. */
export function copyWords(copy: string): CopyButtonWords {
    return { copy, copied: LABELS.action.copy.done }
}

/** What a secret shown once says: its name, its copy button named for it, and that it is shown once. */
export function secretWords(noun: string): SecretRevealWords {
    return { ...copyWords(LABELS.shell.copy_secret(noun)), warning: LABELS.shell.shown_once, secret: noun }
}

/** What a search box says while it is empty, wherever one is drawn. */
export const SEARCH_PLACEHOLDER = LABELS.shell.search

/** What a search box's clear button is called. */
export const SEARCH_WORDS: SearchFieldWords = { clear: LABELS.shell.clear_search }

/** The one dismissal word a dialog's footer says. */
export const DIALOG_WORDS: Partial<DialogShellWords> = { cancel: LABELS.action.cancel }

/** What a link out of this app says to a screen reader after its text. */
export const LINK_WORDS: TextLinkWords = { newTab: LABELS.shell.new_tab }

/** What a split button's chevron is called: "More ways to create a pipeline". */
export function splitWords(more: string): SplitButtonWords {
    return { more }
}

/** One section of the gallery, by the id its heading and its index entry share. */
export type GallerySection =
    | 'titles'
    | 'headings'
    | 'links'
    | 'labels'
    | 'dots'
    | 'icons'
    | 'buttons'
    | 'search'
    | 'forms'
    | 'switches'
    | 'notices'
    | 'dialogs'
    | 'facts'

/** The gallery's index: what somebody is looking for, in the order the page draws it. */
export const GALLERY_INDEX: readonly {
    group: 'text' | 'marks' | 'controls' | 'containers'
    sections: readonly GallerySection[]
}[] = [
    { group: 'text', sections: ['titles', 'headings', 'links'] },
    { group: 'marks', sections: ['labels', 'dots', 'icons'] },
    { group: 'controls', sections: ['buttons', 'search', 'forms', 'switches'] },
    { group: 'containers', sections: ['notices', 'dialogs', 'facts'] },
]

/** The anchor of one gallery section, which is what its index entry links to. */
export function galleryAnchor(section: GallerySection): string {
    return `ds-${section}`
}
