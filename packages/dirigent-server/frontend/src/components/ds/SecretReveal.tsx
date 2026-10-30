import { useEffect, useState } from 'react'

import { IconButton } from '@/components/ds/IconButton'
import { Well } from '@/components/ds/Well'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'

/** How long the copy button says it copied before it offers to copy again. */
const COPIED_MS = 2000

/**
 * A secret the server answers with once -- a minted token, a webhook signing key -- and the
 * one place it is drawn.
 *
 * The value in mono, selectable and wrapping, a copy button that says it copied and resets,
 * and the line saying it is shown once. `label` names the secret for the copy button.
 */
export function SecretReveal({ value, label }: { value: string; label: string }) {
    const [copied, setCopied] = useState(false)
    useEffect(() => {
        if (!copied) return
        const clock = setTimeout(() => {
            setCopied(false)
        }, COPIED_MS)
        return () => {
            clearTimeout(clock)
        }
    }, [copied])
    return (
        <Well className="space-y-2">
            <div className="flex items-start gap-2">
                <code className="min-w-0 flex-1 rounded-sm bg-field px-2 py-1.5 font-mono text-xs break-all select-all">
                    {value}
                </code>
                <IconButton
                    icon={copied ? ICONS.done : ICONS.copy}
                    label={copied ? LABELS.action.copy.done : LABELS.shell.copy_secret(label)}
                    variant="outline"
                    onClick={() => {
                        void navigator.clipboard.writeText(value).then(
                            () => {
                                setCopied(true)
                            },
                            () => {
                                setCopied(false)
                            },
                        )
                    }}
                />
            </div>
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <ICONS.secret className="size-3.5 shrink-0" aria-hidden />
                {LABELS.shell.shown_once}
            </p>
        </Well>
    )
}
