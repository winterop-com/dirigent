import { useEffect, useState } from 'react'

/**
 * How wide an element is, followed as it changes.
 *
 * ONE OBSERVER, NOT ONE PER ROW. What a cell can do with the width is a decision every row
 * takes against the same number, so the observer belongs on the box that has the width --
 * the listing's own card -- and the rows read it from there.
 *
 * A width nothing has measured yet is 0, which is the answer before the observer's first
 * callback and what a caller reads as "no bound to work to". The observer reports the element's
 * current size as soon as it is given one, so that answer lasts a frame.
 */
export function useElementWidth(element: HTMLElement | null): number {
    const [width, setWidth] = useState(0)

    useEffect(() => {
        if (element === null || typeof ResizeObserver === 'undefined') return
        const observer = new ResizeObserver((entries) => {
            const box = entries[0]?.contentRect
            if (box !== undefined) setWidth(box.width)
        })
        observer.observe(element)
        return () => {
            observer.disconnect()
        }
    }, [element])

    return width
}
