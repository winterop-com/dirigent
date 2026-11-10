import type { ReactNode } from 'react'

import { WindowedPane } from '@winterop-com/sokkel-ui/WindowedPane'
import { useControlledDocument } from '@winterop-com/sokkel-ui/CodeEditor'
import { CodePane } from '@/components/pipeline/CodePane'
import { windowWords } from '@/lib/design-system'

/**
 * A program in a field-sized box that opens in a window. The box stays in place while the window
 * is open, and the two are views of one buffer: what is typed in either is what the other shows,
 * and closing the window loses nothing.
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
    const buffer = useControlledDocument(value, onChange)
    return (
        <div className="contents" onBlur={onBlur}>
            <WindowedPane
                title={<span className="font-mono">{name}</span>}
                keepPane
                aside={aside}
                words={windowWords(name)}
            >
                {(where) =>
                    where === 'pane' ? (
                        <CodePane
                            doc={buffer}
                            mediaType={mediaType}
                            label={label}
                            placeholder={placeholder}
                            className={className}
                            readOnly={readOnly}
                        />
                    ) : (
                        <CodePane
                            doc={buffer}
                            mediaType={mediaType}
                            label={windowLabel}
                            className="min-h-0 flex-1"
                            readOnly={readOnly}
                        />
                    )
                }
            </WindowedPane>
        </div>
    )
}
