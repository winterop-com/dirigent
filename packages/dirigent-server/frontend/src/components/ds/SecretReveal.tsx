import { CopyButton } from '@/components/ds/CopyButton'
import { Well } from '@/components/ds/Well'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'

/**
 * A secret the server answers with once -- a minted token, a webhook signing key -- and the
 * one place it is drawn.
 *
 * The value in mono, selectable and wrapping, a copy button that says it copied and resets,
 * and the line saying it is shown once. `label` names the secret for the copy button.
 */
export function SecretReveal({ value, label }: { value: string; label: string }) {
    return (
        <Well className="space-y-2">
            <div className="flex items-start gap-2">
                <code className="min-w-0 flex-1 rounded-sm bg-field px-2 py-1.5 font-mono text-xs break-all select-all">
                    {value}
                </code>
                <CopyButton value={value} label={LABELS.shell.copy_secret(label)} />
            </div>
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <ICONS.secret className="size-3.5 shrink-0" aria-hidden />
                {LABELS.shell.shown_once}
            </p>
        </Well>
    )
}
