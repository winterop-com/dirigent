/**
 * What somebody has typed into the form that mints a connection, and what it amounts to.
 *
 * THE FORM HAS TWO SURFACES AND ONE SET OF DECISIONS. A credential is minted from the
 * Connections screen's dialog, where the code and the kind are asked for, and from the row of
 * the Apply dialog's offer that says the document names a connection this instance has not got,
 * where both are the document's and the row already draws them. What differs between the two is
 * which controls are drawn; what a draft sends and why Create is shut do not, so they are here.
 *
 * THE IDENTITY IS SETTLED BEFORE THE SETTINGS ARE. A config belongs to its kind, so the kind is
 * what decides which controls exist at all. The settings, secrets among them, are the kind's
 * schema form's own value, and the draft holds what is around them.
 */

import type { JsonMap } from '@/lib/api'
import type { ConnectionIn } from '@/lib/connections'
import { LABELS } from '@/lib/labels'

/** One connection being typed: what it will be called, what kind it is, and what it is about. */
export interface ConnectionDraft {
    /** The code it will be addressed by, which is what every reference to it names. */
    code: string
    kind: string
    /** The optional human title, empty where nobody gave it one. */
    name: string
    description: string
}

/** A draft with nothing in it, which is what the dialog opens on. */
export const NO_DRAFT: ConnectionDraft = {
    code: '',
    kind: '',
    name: '',
    description: '',
}

/** A draft on an identity the caller already knows, which is what a document's row hands it. */
export function draftFor(code: string, kind: string | null): ConnectionDraft {
    return { ...NO_DRAFT, code, kind: kind ?? '' }
}

/** What creating this connection sends, its settings as the kind's form holds them. `ConnectionIn`. */
export function connectionBody(draft: ConnectionDraft, config: JsonMap): ConnectionIn {
    return {
        code: draft.code.trim(),
        name: given(draft.name),
        kind: draft.kind,
        description: given(draft.description),
        config,
    }
}

/**
 * Why Create is shut, in the order the form decides it, or nothing when it would work.
 *
 * A FORM THAT IS NOT FILLED IN YET IS NOT A CONTROL THAT CANNOT ACT. Every sentence here is a
 * forward path that exists and is not ready, so the button stays drawn and shut and filling the
 * form opens it.
 */
export function createShut(draft: ConnectionDraft): string | undefined {
    if (draft.code.trim() === '') return LABELS.connections.needs_code
    if (draft.kind === '') return LABELS.connections.needs_kind
    return undefined
}

/** A box that was emptied is that member cleared, not a member set to "". */
function given(text: string): string | null {
    const trimmed = text.trim()
    return trimmed === '' ? null : trimmed
}
