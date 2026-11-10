import { useMemo } from 'react'

import {
    CodeEditor as LibraryCodeEditor,
    defineLanguage,
    languageForMediaType,
    type CodeLanguage,
    type CodeMark,
    type SharedDocument,
} from '@winterop-com/sokkel-ui/CodeEditor'
import { JSON_SCHEMA_2020_12 } from '@winterop-com/sokkel-ui/json-schema'

import { useStore } from '@/hooks/use-store'
import type { JsonMap } from '@/lib/api'
import { SCHEMA_CHECK_WORDS } from '@/lib/design-system'
import { highlightLine } from '@/lib/preferences'
import { cqlParser, fhirpathParser } from '@/lib/program-grammars'

/**
 * The editor every piece of source in this app is written in: a pipeline document, a schema, and
 * a config field whose schema says it carries a program.
 *
 * A buffer handed a `schema` is checked and completed against it as it is typed; `GET
 * /schema/document` answers with `dirigent/v1` composed with this instance's own block config
 * schemas, so a key no block takes is marked where it was typed. A buffer holding
 * `application/schema+json` is checked against the JSON Schema 2020-12 meta-schema, carried
 * rather than fetched. The row under the caret is shaded only when the reader's preference asks
 * for it.
 *
 * The language comes from the media type the field's schema published, YAML when none is named.
 * FHIRPath and CQL are this app's own grammars; every other media type is the editor's to read,
 * and one it does not know is plain text.
 */

const FHIRPATH = defineLanguage(fhirpathParser)
const CQL = defineLanguage(cqlParser)

const SCHEMA_DOCUMENT = 'application/schema+json'

const OWN_LANGUAGES: Record<string, CodeLanguage> = {
    'application/fhirpath': FHIRPATH,
    'text/cql': CQL,
}

/** The language a buffer of this media type is read in. */
export function languageOf(mediaType: string | null | undefined): CodeLanguage {
    if (mediaType === null || mediaType === undefined) return 'yaml'
    return OWN_LANGUAGES[mediaType] ?? languageForMediaType(mediaType)
}

/** A range of the buffer a check refused, by character offset, and why. */
export interface EditorMark {
    start: number
    end: number
    message: string
}

export function CodeEditor({
    value,
    doc,
    schema,
    mediaType,
    label,
    placeholder,
    className,
    variant = 'field',
    readOnly = false,
    marks,
    reveal,
    wrap = false,
    deferred,
    onChange,
}: {
    /** The text, for a buffer drawn once; left out when `doc` is given. */
    value?: string
    /** A buffer shared with another view of it, such as a pane and its window. */
    doc?: SharedDocument
    /** The JSON Schema every edit is checked against, null when it could not be read, and nothing
     * at all when this buffer is not schema-checked. */
    schema?: JsonMap | null
    /** What this buffer holds, as the schema published it. YAML when a caller names none. */
    mediaType?: string | null
    /** What a screen reader and a test call this editor. */
    label: string
    /** What an empty editor shows instead of nothing at all. */
    placeholder?: string
    /** How tall the editor is drawn, which is the one thing its callers disagree about. */
    className?: string
    /** `field` is boxed like an input; `pane` fills a panel of its own, edge to edge. */
    variant?: 'field' | 'pane'
    /** A buffer nobody may type into, which is what a viewer of produced data asks for. */
    readOnly?: boolean
    /** Ranges of the buffer a check refused, by character offset, each saying why on hover. */
    marks?: readonly EditorMark[]
    /** A range to select and bring into view; a new object moves there again. */
    reveal?: { start: number; end: number } | null
    /** Long lines wrap at the pane's edge instead of running past it. */
    wrap?: boolean
    /** A value the schema leaves unchecked, because the run fills it in. */
    deferred?: (value: unknown) => boolean
    onChange?: (text: string) => void
}) {
    const language = languageOf(mediaType)
    const activeLine = useStore(highlightLine)
    const checkedAgainst = mediaType === SCHEMA_DOCUMENT ? JSON_SCHEMA_2020_12 : (schema ?? undefined)
    const codeMarks = useMemo<readonly CodeMark[] | undefined>(
        () =>
            marks?.map((mark) => ({
                from: mark.start,
                to: Math.max(mark.end, mark.start + 1),
                tone: 'error',
                message: mark.message,
            })),
        [marks],
    )
    const range = useMemo(
        () => (reveal === null || reveal === undefined ? reveal : { from: reveal.start, to: reveal.end }),
        [reveal],
    )
    return (
        <LibraryCodeEditor
            value={doc === undefined ? value : undefined}
            doc={doc}
            onChange={onChange}
            language={language}
            schema={checkedAgainst}
            words={SCHEMA_CHECK_WORDS}
            deferred={deferred}
            label={label}
            placeholder={placeholder}
            readOnly={readOnly}
            marks={codeMarks}
            reveal={range}
            wrap={wrap}
            activeLine={activeLine}
            size="sm"
            variant={variant}
            search
            folding
            className={className}
        />
    )
}
