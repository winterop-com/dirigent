import { useEffect, useRef } from 'react'

import { useSharedDocument, type SharedDocument } from '@winterop-com/sokkel-ui/CodeEditor'

/**
 * One buffer for every view of a text, such as a pane and its window, held in step with `value`.
 *
 * A `value` that changed anywhere else replaces the buffer's text; an edit in any view is
 * reported once through `onChange`, however many views draw the buffer.
 */
export function useCodeBuffer(value: string, onChange?: (text: string) => void): SharedDocument {
    const doc = useSharedDocument(value)
    const held = useRef(value)
    const report = useRef(onChange)

    useEffect(() => {
        report.current = onChange
    })

    useEffect(
        () =>
            doc.subscribe((text) => {
                if (text === held.current) return
                held.current = text
                report.current?.(text)
            }),
        [doc],
    )

    useEffect(() => {
        if (value === held.current) return
        held.current = value
        doc.setText(value)
    }, [doc, value])

    return doc
}
