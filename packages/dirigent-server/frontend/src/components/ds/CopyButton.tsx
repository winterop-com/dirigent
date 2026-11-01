import { useEffect, useState } from 'react'

import { IconButton } from '@/components/ds/IconButton'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'

/** How long the button says it copied before it offers to copy again. */
const COPIED_MS = 2000

/**
 * The icon button that puts one string on the clipboard, says it copied, and resets.
 *
 * `label` is what it offers before it is pressed. Where the origin has no clipboard the press
 * changes nothing, and the string beside it is still on screen to be selected.
 */
export function CopyButton({
    value,
    label,
    size = 'md',
    variant = 'outline',
}: {
    value: string
    label: string
    size?: 'xs' | 'sm' | 'md'
    variant?: 'ghost' | 'outline'
}) {
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
        <IconButton
            icon={copied ? ICONS.done : ICONS.copy}
            label={copied ? LABELS.action.copy.done : label}
            size={size}
            variant={variant}
            onClick={() => {
                void navigator.clipboard?.writeText(value).then(
                    () => {
                        setCopied(true)
                    },
                    () => {
                        setCopied(false)
                    },
                )
            }}
        />
    )
}
