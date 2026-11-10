import type { ReactNode } from 'react'

import { CodePane } from '@/components/pipeline/CodePane'
import { WindowedPane } from '@/components/WindowedPane'
import { useCodeBuffer } from '@/hooks/use-code-buffer'

/**
 * A program in a field-sized box that opens in a window. The box and the window are two views of
 * one buffer: what is typed in either is what the other shows, and closing the window loses
 * nothing.
 */
export function WindowedSource({
    name,
    label,
    windowLabel,
    value,
    mediaType,
    placeholder,
    className,
    readOnly = false,
    aside,
    onBlur,
    onChange,
}: {
    /** The window's title, and what its button names. */
    name: string
    label: string
    windowLabel: string
    value: string
    mediaType: string | null
    placeholder?: string
    /** How tall the box is. */
    className: string
    readOnly?: boolean
    /** A reference for the language, beside the editor in the window. */
    aside?: ReactNode
    onBlur?: () => void
    onChange: (text: string) => void
}) {
    const buffer = useCodeBuffer(value, onChange)
    return (
        <WindowedPane
            name={name}
            onBlur={onBlur}
            aside={aside}
            windowed={
                <CodePane
                    doc={buffer}
                    mediaType={mediaType}
                    label={windowLabel}
                    className="min-h-0 flex-1"
                    readOnly={readOnly}
                />
            }
        >
            <CodePane
                doc={buffer}
                mediaType={mediaType}
                label={label}
                placeholder={placeholder}
                className={className}
                readOnly={readOnly}
            />
        </WindowedPane>
    )
}
