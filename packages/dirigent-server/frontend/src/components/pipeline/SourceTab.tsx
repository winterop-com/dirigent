import { useEffect, useMemo, useRef, useState } from 'react'

import { CodePane } from '@/components/pipeline/CodePane'
import type { JsonMap } from '@/lib/api'
import { toYaml } from '@/lib/pipeline-document'

/**
 * The document as text, which is the form it is written in everywhere else.
 *
 * IT IS THE SAME DOCUMENT AS THE OTHER TWO TABS. Typing here parses and becomes the local
 * document, and editing a field over there re-renders here, so there is one document and three
 * ways of reading it rather than three documents.
 *
 * TEXT THAT IS NOT A DOCUMENT IS KEPT. While it does not parse, the local document is the last
 * one that did and no other tab may write to it -- a form quietly replacing half-fixed text is
 * worse than a form that says it cannot.
 *
 * THE YAML IS RENDERED HERE, NOT SERVED. `GET /pipelines/{name}/$export` is the canonical text
 * and orders the steps topologically; this renders the document as it stands, in the order it is
 * held in, so what is edited and what is read back are the same thing. An apply canonicalises it.
 */

/** Which buffer this pane edits, and what a screen reader and a test call it. */
const DOCUMENT_PATH = 'document'
const DOCUMENT_LABEL = 'The document'

/** How long after the last keystroke the text is read as a document. */
const SETTLE_MS = 250

export function SourceTab({
    document,
    schema,
    parseError,
    onWrite,
    readOnly = false,
}: {
    /** The local document, or null when the pipeline has no version yet. */
    document: JsonMap | null
    /** The JSON Schema the editor checks against, or null when it could not be read. */
    schema: JsonMap | null
    /** Why the text in the pane is not a document, or null. */
    parseError: string | null
    onWrite: (text: string) => void
    /** Below the breakpoint a document is read rather than written. */
    readOnly?: boolean
}) {
    const rendered = useMemo(() => (document === null ? '' : toYaml(document)), [document])
    const [text, setText] = useState(rendered)
    const typed = useRef(false)
    const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

    // The document changed somewhere else, so the pane shows it -- unless this pane is what
    // changed it, in which case the text it holds is already ahead of the render.
    useEffect(() => {
        if (typed.current) return
        setText(rendered)
    }, [rendered])

    useEffect(() => {
        return () => {
            if (timer.current !== null) clearTimeout(timer.current)
        }
    }, [])

    if (document === null) {
        return (
            <p className="p-4 text-sm text-muted-foreground">
                This pipeline has no version, so there is no document to read.
            </p>
        )
    }

    return (
        <div className="flex h-full min-h-0 flex-col">
            {parseError !== null && (
                <div className="border-b border-border p-2 text-xs text-critical" role="alert">
                    <pre className="overflow-x-auto font-mono whitespace-pre-wrap">{parseError}</pre>
                    <p className="mt-1">The other tabs are showing the last document that parsed.</p>
                </div>
            )}
            <div className="min-h-0 flex-1">
                <CodePane
                    value={text}
                    schema={schema}
                    path={DOCUMENT_PATH}
                    label={DOCUMENT_LABEL}
                    readOnly={readOnly}
                    onChange={(next) => {
                        typed.current = true
                        setText(next)
                        if (timer.current !== null) clearTimeout(timer.current)
                        timer.current = setTimeout(() => {
                            typed.current = false
                            onWrite(next)
                        }, SETTLE_MS)
                    }}
                />
            </div>
        </div>
    )
}
