import { useCallback, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'

/** Which way an edge is dragged: a panel's width along x, a drawer's height along y. */
export type DragAxis = 'x' | 'y'

/**
 * Follow a drag on an edge and write the size it expresses: the run terminal's top edge.
 *
 * The drag is followed on the document rather than on the handle, so the pointer leaving the
 * few-pixel strip mid-drag does not drop it. While the pointer moves, the size is written to
 * the element's own style, because a React render per pointer event leaves the edge visibly
 * behind the hand; the store hears the size once per frame. `grows` says which way the element
 * gains: 1 for an edge dragged away from the origin, and -1 for one dragged toward it, which is a
 * drawer's top edge.
 */
export function useDragSize(
    axis: DragAxis,
    size: number,
    grows: 1 | -1,
    set: (size: number) => void,
    clamp: (size: number) => number,
    element: RefObject<HTMLElement | null>,
) {
    const [dragging, setDragging] = useState(false)
    const start = useRef({ at: 0, size: 0 })

    const beginResize = useCallback(
        (event: ReactPointerEvent<HTMLDivElement>) => {
            event.preventDefault()
            const along = (point: { clientX: number; clientY: number }) =>
                axis === 'x' ? point.clientX : point.clientY
            start.current = { at: along(event), size }
            setDragging(true)
            let latest = size
            let frame: number | null = null
            const follow = (move: globalThis.PointerEvent) => {
                latest = clamp(start.current.size + grows * (along(move) - start.current.at))
                if (element.current) {
                    if (axis === 'x') element.current.style.width = `${String(latest)}px`
                    else element.current.style.height = `${String(latest)}px`
                }
                frame ??= requestAnimationFrame(() => {
                    frame = null
                    set(latest)
                })
            }
            const release = () => {
                document.removeEventListener('pointermove', follow)
                document.removeEventListener('pointerup', release)
                if (frame !== null) cancelAnimationFrame(frame)
                setDragging(false)
                set(latest)
            }
            document.addEventListener('pointermove', follow)
            document.addEventListener('pointerup', release)
        },
        [axis, size, grows, set, clamp, element],
    )

    return { dragging, beginResize }
}
