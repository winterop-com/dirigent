import * as monaco from 'monaco-editor/esm/vs/editor/editor.api'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import { configureMonacoYaml, type MonacoYaml } from 'monaco-yaml'
import yamlWorker from 'monaco-yaml/yaml.worker?worker'
import { useTheme } from 'next-themes'
import { useEffect, useRef } from 'react'

import type { JsonMap } from '@/lib/api'
import { cn } from '@/lib/utils'

import 'monaco-editor/esm/vs/basic-languages/shell/shell.contribution'
import 'monaco-editor/esm/vs/basic-languages/twig/twig.contribution'
import 'monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution'
import 'monaco-editor/esm/vs/language/json/monaco.contribution'

/**
 * The editor every piece of source in this app is written in: a pipeline document, and a config
 * field whose schema says it carries a program.
 *
 * WHY A LANGUAGE SERVER AND NOT A TEXTAREA. `GET /schema/document` answers with `dirigent/v1`
 * composed with this instance's own block config schemas, so `monaco-yaml` marks a key no block
 * takes at the character it was typed at -- which is the same place an apply refuses it, said
 * before the apply is asked for. A schema-checked buffer is what `schema` asks for; a buffer
 * that names none is edited without one, and the singleton below is left as it was found.
 *
 * A FIELD IS SOURCE WHEN ITS SCHEMA SAYS SO. A block config field carrying `contentMediaType`
 * holds a program, and `LANGUAGES` is the whole of what this app does with one: the language
 * monaco tokenises it as, and the extension its buffer is named with. A media type monaco has
 * no language for is edited as plain text, which is a mono font and no colour -- honest for jq,
 * which monaco does not ship.
 *
 * IT IS LOADED IN ITS OWN CHUNK. Monaco and its two workers are the largest thing this app can
 * pull, so nothing imports this file by name: `CodePane` beside it is the one dynamic import,
 * and the source tab, the apply dialog and a step's program field all reach the editor
 * through it.
 *
 * EVERY EDITOR HAS ITS OWN MODEL. A model is registered under a uri and monaco holds one
 * instance per uri, so two panes sharing a path would share a buffer -- the caller names the
 * buffer it is editing and gets one of its own.
 *
 * MONACO WEARS THE HOUSE PALETTE. It cannot read custom properties itself, so the theme is
 * built from them: each token the theme needs is resolved by the browser off the live page
 * and handed over as a literal, rebuilt when the mode flips. The hues are the ones the
 * step panel's inline JSON already wears, so a value reads the same at every size.
 *
 * ONLY THE EDITOR AND THE LANGUAGES IT HOSTS ARE IMPORTED. `monaco-editor` as a whole registers
 * every language it ships; what is wanted is the editor plus YAML, shell and twig, so the api
 * entry and those three contributions are imported by path and the rest are never fetched. A
 * language `LANGUAGES` names but nothing imported tokenises as plain text and says nothing.
 */

/** Which worker each language runs in. `self` carries this: monaco reads it off the global. */
const environment: monaco.Environment = {
    getWorker(_workerId: string, label: string) {
        if (label === 'yaml') return new yamlWorker()
        if (label === 'json') return new jsonWorker()
        return new editorWorker()
    },
}
;(self as unknown as { MonacoEnvironment: monaco.Environment }).MonacoEnvironment = environment

/** How a buffer is tokenised and what it is named, which is all a media type decides here. */
interface Buffer {
    language: string
    extension: string
}

/** What a document pane edits, which is what a caller naming no media type gets. */
const YAML: Buffer = { language: 'yaml', extension: 'yaml' }

/** A language monaco does not ship: mono, and no colour. */
const PLAIN: Buffer = { language: 'plaintext', extension: 'txt' }

const LANGUAGES: Record<string, Buffer> = {
    'text/x-shellscript': { language: 'shell', extension: 'sh' },
    // Jinja is Twig's grammar in everything a template here writes: the same `{{ }}`, `{% %}`
    // and `{# #}` delimiters, and monaco ships Twig.
    'text/x-jinja': { language: 'twig', extension: 'j2' },
    'application/jq': { language: 'plaintext', extension: 'jq' },
    'application/json': { language: 'json', extension: 'json' },
}

/**
 * One css colour as monaco will take it, resolved by the browser.
 *
 * A canvas normalises whatever the stylesheet said -- oklch included -- into bytes, which
 * is the one spelling monaco accepts everywhere.
 */
function resolvedColor(reference: string): string {
    const probe = document.createElement('span')
    probe.style.color = reference
    probe.style.display = 'none'
    document.body.appendChild(probe)
    const said = getComputedStyle(probe).color
    probe.remove()
    const canvas = document.createElement('canvas')
    canvas.width = 1
    canvas.height = 1
    const paint = canvas.getContext('2d')
    if (paint === null) return '#808080'
    paint.fillStyle = said
    paint.fillRect(0, 0, 1, 1)
    const [r, g, b] = paint.getImageData(0, 0, 1, 1).data
    return `#${[r, g, b].map((part) => part.toString(16).padStart(2, '0')).join('')}`
}

/** The house theme, read off the live page so it matches whichever palette is standing. */
function houseTheme(dark: boolean): monaco.editor.IStandaloneThemeData {
    const ink = {
        ground: resolvedColor('var(--color-background)'),
        text: resolvedColor('var(--color-foreground)'),
        quiet: resolvedColor('var(--color-muted-foreground)'),
        key: resolvedColor('var(--color-info-ink)'),
        string: resolvedColor('var(--color-good-ink)'),
        number: resolvedColor('var(--color-warning-ink)'),
        accent: resolvedColor('var(--color-accent)'),
    }
    return {
        base: dark ? 'vs-dark' : 'vs',
        inherit: true,
        // The base theme carries its own rules for JSON's tokens, and a more specific token
        // selector wins over a general one, so each JSON token is named here too.
        rules: [
            { token: 'string.key.json', foreground: ink.key },
            { token: 'string.value.json', foreground: ink.string },
            { token: 'number.json', foreground: ink.number },
            { token: 'keyword.json', foreground: ink.number },
            { token: 'delimiter.bracket.json', foreground: ink.quiet },
            { token: 'delimiter.array.json', foreground: ink.quiet },
            { token: 'delimiter.colon.json', foreground: ink.quiet },
            { token: 'delimiter.comma.json', foreground: ink.quiet },
            { token: 'type', foreground: ink.key },
            { token: 'variable', foreground: ink.key },
            { token: 'string', foreground: ink.string },
            { token: 'number', foreground: ink.number },
            { token: 'keyword', foreground: ink.number },
            { token: 'comment', foreground: ink.quiet },
            { token: 'delimiter', foreground: ink.quiet },
        ],
        colors: {
            'editor.background': ink.ground,
            'editor.foreground': ink.text,
            'editorLineNumber.foreground': ink.quiet,
            'editorLineNumber.activeForeground': ink.text,
            'editor.selectionBackground': ink.accent,
            'editorCursor.foreground': ink.text,
            'editorBracketHighlight.foreground1': ink.quiet,
            'editorBracketHighlight.foreground2': ink.quiet,
            'editorBracketHighlight.foreground3': ink.quiet,
            'editorBracketHighlight.foreground4': ink.quiet,
            'editorBracketHighlight.foreground5': ink.quiet,
            'editorBracketHighlight.foreground6': ink.quiet,
        },
    }
}

/** How one media type is edited. */
function bufferOf(mediaType: string | null | undefined): Buffer {
    if (mediaType === null || mediaType === undefined) return YAML
    return LANGUAGES[mediaType] ?? PLAIN
}

/** The uri a model is registered under, which is what the schema's `fileMatch` matches. */
function modelUri(path: string, buffer: Buffer): string {
    return `inmemory://dirigent/${path}.${buffer.extension}`
}

/** There may only be one configured instance of monaco-yaml at a time. */
let configured: MonacoYaml | null = null

/**
 * Point monaco-yaml at the schema this instance published, or take its schemas away.
 *
 * A pane that names no schema at all is not schema-checked and says nothing here, so a program
 * field opening beside a document pane does not take that pane's schema off it.
 */
function useSchema(schema: JsonMap | null | undefined): void {
    useEffect(() => {
        if (schema === undefined) return
        const schemas =
            schema === null ? [] : [{ uri: 'inmemory://dirigent/schema.json', fileMatch: ['*'], schema }]
        if (configured === null) {
            configured = configureMonacoYaml(monaco, { enableSchemaRequest: false, validate: true, schemas })
            return
        }
        void configured.update({ schemas })
    }, [schema])
}

export function CodeEditor({
    value,
    schema,
    mediaType,
    path,
    label,
    placeholder,
    className,
    readOnly = false,
    onChange,
}: {
    value: string
    /** The JSON Schema every edit is checked against, null when it could not be read, and nothing
     * at all when this buffer is not schema-checked. */
    schema?: JsonMap | null
    /** What this buffer holds, as the schema published it. YAML when a caller names none. */
    mediaType?: string | null
    /** Which buffer this is, which is the model it gets. */
    path: string
    /** What a screen reader and a test call this editor. */
    label: string
    /** What an empty editor shows instead of nothing at all. */
    placeholder?: string
    /** How tall the editor is drawn, which is the one thing its callers disagree about. */
    className?: string
    /** A buffer nobody may type into, which is what a viewer of produced data asks for. */
    readOnly?: boolean
    onChange?: (text: string) => void
}) {
    const host = useRef<HTMLDivElement | null>(null)
    const editor = useRef<monaco.editor.IStandaloneCodeEditor | null>(null)
    const emitted = useRef(value)
    const { resolvedTheme } = useTheme()

    useSchema(schema)

    useEffect(() => {
        if (host.current === null) return
        const buffer = bufferOf(mediaType)
        const uri = monaco.Uri.parse(modelUri(path, buffer))
        const model = monaco.editor.getModel(uri) ?? monaco.editor.createModel(value, buffer.language, uri)
        const created = monaco.editor.create(host.current, {
            model,
            automaticLayout: true,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            fontSize: 12,
            lineNumbers: 'on',
            tabSize: 2,
            renderLineHighlight: 'none',
            bracketPairColorization: { enabled: false },
            scrollbar: { alwaysConsumeMouseWheel: false },
            ariaLabel: label,
            placeholder,
            readOnly,
        })
        editor.current = created
        const watch = model.onDidChangeContent(() => {
            emitted.current = model.getValue()
            onChange?.(emitted.current)
        })
        return () => {
            watch.dispose()
            created.dispose()
            // Two panes may read one buffer -- a config field and its window -- so the model
            // is disposed by whichever editor leaves it last, never from under the other.
            const held = monaco.editor.getEditors().some((editor) => editor.getModel() === model)
            if (!held) model.dispose()
        }
        // The editor is created once. What flows in afterwards is handled by the effects below.
        // oxlint-disable-next-line react/exhaustive-deps
    }, [])

    // A value changed anywhere else -- a config field, a step added, another step chosen -- is
    // written into the model. What this pane itself typed is already there, and rewriting it
    // would move the caret.
    useEffect(() => {
        const model = editor.current?.getModel()
        if (model === null || model === undefined) return
        if (value === emitted.current || value === model.getValue()) return
        emitted.current = value
        model.setValue(value)
    }, [value])

    // The theme is built from the live page's own custom properties, and the class next-themes
    // writes on the root element lands in an effect of its own -- a child's effect runs first,
    // so reading the colours here would read the mode being left rather than the one arriving.
    // The rebuild waits for the frame the new class is painted in.
    useEffect(() => {
        const frame = requestAnimationFrame(() => {
            monaco.editor.defineTheme('dirigent', houseTheme(document.documentElement.classList.contains('dark')))
            monaco.editor.setTheme('dirigent')
        })
        return () => {
            cancelAnimationFrame(frame)
        }
    }, [resolvedTheme])

    return <div ref={host} className={cn('h-full min-h-64 w-full', className)} data-testid="code-editor" />
}
