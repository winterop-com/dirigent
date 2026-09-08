import { Waypoints } from 'lucide-react'
import type { Ref } from 'react'

import { BrandGraph } from '@/components/login/BrandGraph'

/**
 * The half of the door that says what is behind it.
 *
 * DARK IN BOTH PALETTES, like the run terminal and for the same reason: what this pane is is a
 * ground the identity sits on, and turning it over with the rest of the app would make it read
 * as another card rather than as the mark. The light palette meets it as a hard edge against
 * near-white, the dark palette as one rung below the shell.
 *
 * THE AMBER IS SPENT ON THE MARK AND ON THE ONE RUN LIT IN THE GRAPH BEHIND IT. Nothing on this
 * screen acts except the button in the pane beside it, so the colour that means action is not
 * spent on anything else here.
 *
 * THE LOCKUP AND THE FACTS ARE ANCHORED TO THE FOOT AND THE GRAPH TAKES WHAT IS LEFT. The lockup
 * stands a fixed distance above the facts and the facts a fixed distance above the foot, so
 * neither moves an inch between a short pane and a tall one; the graph runs from below the top
 * to a fixed gap above the lockup, and is laid out to that box rather than scaled into it.
 *
 * THE MARK IS ONE SIZE FROM md UP, because the run behind it is what the pane is for: a lockup
 * that grew with the pane would be the largest thing on it.
 *
 * THE FACTS ARE THE ONES A DOOR CAN KNOW. `/config.json` is unauthenticated and carries the
 * version; the instance's environment is behind `/system/info`, which asks who is calling. So
 * the host somebody typed and the version that host answered with are what say which instance
 * this is.
 */
export function BrandPane({
    version,
    ref,
}: {
    version: string | null
    /** The screen measures the pane, because the seam beside it is dragged in pixels. */
    ref?: Ref<HTMLElement>
}) {
    return (
        <aside
            ref={ref} className="bg-terminal text-terminal-foreground relative flex items-center justify-between gap-4 overflow-hidden px-5 py-6 md:block md:p-0">
            {/* Below md the pane is a strip an inch tall, which a graph drawn to fill it would
                only crowd. The box it spans at md is the pane's full width, 48px below the top,
                and stops a fixed 64px above the lockup: the lockup's own height is what the two
                offsets differ by. */}
            <div className="hidden md:absolute md:inset-x-0 md:top-12 md:bottom-77 md:block xl:bottom-65">
                <BrandGraph />
            </div>
            <div className="relative flex items-center gap-3.5 md:absolute md:right-12 md:bottom-31 md:left-12 md:flex-col md:items-start md:gap-6 xl:right-18 xl:left-18 xl:flex-row xl:items-center xl:gap-7">
                <span className="bg-terminal-accent text-terminal flex size-10 shrink-0 items-center justify-center rounded-lg md:size-18 md:rounded-[1rem]">
                    <Waypoints className="size-5 md:size-10" aria-hidden />
                </span>
                <h1 className="text-base font-semibold tracking-tight xl:text-wordmark">dirigent</h1>
            </div>
            <dl className="relative flex items-baseline gap-x-3 text-xs md:absolute md:right-12 md:bottom-12 md:left-12 md:grid md:grid-cols-[4.5rem_1fr] md:gap-y-1.5 xl:right-18 xl:left-18">
                <dt className="text-terminal-faint sr-only md:not-sr-only">instance</dt>
                <dd className="text-terminal-muted font-mono">{window.location.host}</dd>
                <dt className="text-terminal-faint sr-only md:not-sr-only">version</dt>
                <dd className="text-terminal-muted font-mono">{version ?? ''}</dd>
            </dl>
        </aside>
    )
}
