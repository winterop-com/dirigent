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
 * what decides which controls exist at all -- which is why choosing another kind empties the
 * draft's settings rather than carrying them onto a form they were not typed for.
 *
 * A SECRET IS WRITTEN AND NEVER READ. A draft holds what was typed into a password box as its
 * own member, never among the settings, and `mintedConfig` is what folds the two together at
 * the moment of sending -- so a box nobody touched contributes nothing, rather than a field set
 * to the empty string, which is a password somebody chose.
 */

import type { JsonMap } from '@/lib/api'
import { mintedConfig, type ConnectionIn } from '@/lib/connections'
import { LABELS } from '@/lib/labels'
import { maySubmit } from '@/lib/schema-form'

/** One connection being typed: what it will be called, what kind it is, and what it holds. */
export interface ConnectionDraft {
    /** The code it will be addressed by, which is what every reference to it names. */
    code: string
    kind: string
    /** The optional human title, empty where nobody gave it one. */
    name: string
    description: string
    /** The kind's own settings, as the generated form has written them. */
    values: JsonMap
    /** What was typed into each password box, which no read ever puts back. */
    secrets: Record<string, string>
}

/** A draft with nothing in it, which is what the dialog opens on. */
export const NO_DRAFT: ConnectionDraft = {
    code: '',
    kind: '',
    name: '',
    description: '',
    values: {},
    secrets: {},
}

/** A draft on an identity the caller already knows, which is what a document's row hands it. */
export function draftFor(code: string, kind: string | null): ConnectionDraft {
    return { ...NO_DRAFT, code, kind: kind ?? '' }
}

/**
 * The draft with another kind chosen, which is a different config.
 *
 * What was typed for the last kind goes with it: a setting belongs to the schema that asked for
 * it, and carrying one across would send a key the new kind does not take.
 */
export function withKind(draft: ConnectionDraft, kind: string): ConnectionDraft {
    return { ...draft, kind, values: {}, secrets: {} }
}

/** The draft with one setting written, or with it cleared where the control answered nothing. */
export function withSetting(draft: ConnectionDraft, name: string, value: unknown): ConnectionDraft {
    const values = { ...draft.values }
    if (value === undefined) delete values[name]
    else values[name] = value
    return { ...draft, values }
}

/** The draft with one password box's text held, which is the only way a credential is set. */
export function withSecret(draft: ConnectionDraft, name: string, typed: string): ConnectionDraft {
    return { ...draft, secrets: { ...draft.secrets, [name]: typed } }
}

/** What creating this connection sends. `ConnectionIn`. */
export function connectionBody(draft: ConnectionDraft): ConnectionIn {
    return {
        code: draft.code.trim(),
        name: given(draft.name),
        kind: draft.kind,
        description: given(draft.description),
        config: mintedConfig(draft.values, draft.secrets),
    }
}

/**
 * Why Create is shut, in the order the form decides it, or nothing when it would work.
 *
 * A FORM THAT IS NOT FILLED IN YET IS NOT A CONTROL THAT CANNOT ACT. Every sentence here is a
 * forward path that exists and is not ready, so the button stays drawn and shut and filling the
 * form opens it.
 */
export function createShut(
    draft: ConnectionDraft,
    problems: Record<string, string>,
    unreadable: ReadonlySet<string>,
): string | undefined {
    if (draft.code.trim() === '') return LABELS.connections.needs_code
    if (draft.kind === '') return LABELS.connections.needs_kind
    if (unreadable.size > 0) return LABELS.connections.unreadable_setting
    if (!maySubmit(problems, unreadable)) return LABELS.connections.settings_refused
    return undefined
}

/** A box that was emptied is that member cleared, not a member set to "". */
function given(text: string): string | null {
    const trimmed = text.trim()
    return trimmed === '' ? null : trimmed
}
