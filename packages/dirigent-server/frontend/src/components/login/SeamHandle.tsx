import { useRef, useState, type KeyboardEvent, type PointerEvent } from 'react'

import {
    PANE_BIG_STEP,
    PANE_STEP,
    clampPaneWidth,
    paneBounds,
} from '@/components/login/pane-width'

/** What the separator says it is, for a reader who reaches it by key rather than by pointer. */
export const SEAM_LABEL = 'Resize the brand pane'

/**
 * The seam between the two panes, which is also the handle that moves it.
 *
 * NOTHING IS DRAWN AT REST. The two panes already meet in a hard edge and a second line over it
 * would be chrome for a control almost nobody is looking for; the line appears under the
 * pointer, on focus, and while the seam is being dragged, which are the three moments somebody
 * is asking where it is.
 *
 * IT IS A `separator` AND IT ANSWERS THE KEYS, like every other dragged edge in this app: a
 * handle only a pointer can move is a handle some people cannot move. Escape puts back the width
 * the drag started from, and Backspace or Delete gives the pane its own clamp back -- which is
 * what a double-click does for a pointer.
 */
export function SeamHandle({
    width,
    onChange,
    onReset,
}: {
    /** The pane's width right now, chosen or not, which is what a drag starts from. */
    width: number
    onChange: (width: number) => void
    onReset: () => void
}) {
    const handle = useRef<HTMLDivElement>(null)
    const drag = useRef<{ x: number; width: number } | null>(null)
    const [dragging, setDragging] = useState(false)
    const bounds = paneBounds(window.innerWidth)

    function end(): void {
        drag.current = null
        setDragging(false)
    }

    function onPointerDown(event: PointerEvent<HTMLDivElement>): void {
        if (event.button !== 0) return
        event.preventDefault()
        handle.current?.setPointerCapture(event.pointerId)
        drag.current = { x: event.clientX, width }
        setDragging(true)
    }

    function onPointerMove(event: PointerEvent<HTMLDivElement>): void {
        const from = drag.current
        if (from === null) return
        onChange(clampPaneWidth(from.width + (event.clientX - from.x), window.innerWidth))
    }

    function onPointerUp(event: PointerEvent<HTMLDivElement>): void {
        if (drag.current === null) return
        handle.current?.releasePointerCapture(event.pointerId)
        end()
    }

    function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
        // Escape belongs to the drag, and only to it: a press with nothing in flight is the
        // shell's to answer, not this handle's.
        if (event.key === 'Escape') {
            const from = drag.current
            if (from === null) return
            event.preventDefault()
            onChange(clampPaneWidth(from.width, window.innerWidth))
            end()
            return
        }
        const step = event.shiftKey ? PANE_BIG_STEP : PANE_STEP
        const moved =
            event.key === 'ArrowLeft'
                ? width - step
                : event.key === 'ArrowRight'
                  ? width + step
                  : event.key === 'Home'
                    ? bounds.min
                    : event.key === 'End'
                      ? bounds.max
                      : null
        if (moved !== null) {
            event.preventDefault()
            onChange(clampPaneWidth(moved, window.innerWidth))
            return
        }
        if (event.key === 'Backspace' || event.key === 'Delete') {
            event.preventDefault()
            onReset()
        }
    }

    return (
        <div
            ref={handle}
            role="separator"
            aria-orientation="vertical"
            aria-label={SEAM_LABEL}
            aria-valuemin={bounds.min}
            aria-valuemax={bounds.max}
            aria-valuenow={Math.round(width)}
            tabIndex={0}
            className="group absolute inset-y-0 -left-1 z-10 hidden w-2 cursor-col-resize outline-none lg:block"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onDoubleClick={onReset}
            onKeyDown={onKeyDown}
        >
            <div
                className={`bg-terminal-node-edge mx-auto h-full w-px ${
                    dragging ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100'
                }`}
            />
        </div>
    )
}
