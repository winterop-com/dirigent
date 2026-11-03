import { useEffect, useState } from 'react'

import { FACE_SIZE, measureByCharacters, type Measure, type TextFace } from '@/lib/dag-layout'

/**
 * How wide a node's words are drawn, measured in the faces the page draws them in.
 *
 * A BOX IS SIZED BEFORE IT IS DRAWN. elk is handed every box's width up front, so the words are
 * measured on a canvas of their own in the same font, size and weight the node sets them in. Until
 * the faces have loaded the width is read off the characters, and the canvas is re-measured once
 * they have, so a box is never sized against a fallback font.
 */

/** The font each face is set in, as a canvas states one. */
function fontOf(face: TextFace): string {
    const root = getComputedStyle(document.documentElement)
    const family = root.getPropertyValue(face.endsWith('mono') ? '--font-mono' : '--font-sans').trim()
    const weight = face.startsWith('title') ? 600 : 400
    return `${String(weight)} ${String(FACE_SIZE[face])}px ${family === '' ? 'monospace' : family}`
}

const FACES: readonly TextFace[] = ['title-mono', 'title-sans', 'small-mono', 'small-sans']

/** Whether every face has loaded, held for the life of the tab. */
let loaded = false
let loading: Promise<void> | null = null

/** One canvas context, made on the first measurement. */
let context: CanvasRenderingContext2D | null = null

/** What a run of text measures in one face, cached: a graph asks for the same words every second. */
const widths = new Map<string, number>()

const measureByFont: Measure = (text, face) => {
    const key = `${face}\u0000${text}`
    const held = widths.get(key)
    if (held !== undefined) return held
    context ??= document.createElement('canvas').getContext('2d')
    if (context === null) return measureByCharacters(text, face)
    context.font = fontOf(face)
    const width = Math.ceil(context.measureText(text).width)
    widths.set(key, width)
    return width
}

/** Load every face a node draws in, once. */
function loadFaces(): Promise<void> {
    loading ??= Promise.all(FACES.map((face) => document.fonts.load(fontOf(face)))).then(
        () => {
            loaded = true
        },
        () => {
            loaded = true
        },
    )
    return loading
}

/** The measure a canvas sizes its boxes with: the font's once it has loaded, the characters' until then. */
export function useMeasure(): Measure {
    const [ready, setReady] = useState(loaded)
    useEffect(() => {
        if (ready || typeof document === 'undefined' || !('fonts' in document)) return
        let current = true
        void loadFaces().then(() => {
            if (current) setReady(true)
        })
        return () => {
            current = false
        }
    }, [ready])
    return ready ? measureByFont : measureByCharacters
}

/** Whether a measure is the font's, which is the last a canvas's boxes are sized by. */
export function measuresByFont(measure: Measure): boolean {
    return measure === measureByFont
}
