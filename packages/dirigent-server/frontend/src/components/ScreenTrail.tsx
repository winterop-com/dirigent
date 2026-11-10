import { useEffect, useState } from 'react'

import { clearScreenTrail, sameTrail, setScreenTrail, type Crumb } from '@/lib/trail'

/**
 * States a screen's trail to the top bar for as long as the screen is mounted, so the page
 * opens on its heading and the trail stands in the shell's bar. Draws nothing where it is put.
 */
export function ScreenTrail({ trail }: { trail: readonly Crumb[] }) {
    const [held, setHeld] = useState(trail)
    if (!sameTrail(held, trail)) setHeld(trail)
    useEffect(() => {
        setScreenTrail(held)
    }, [held])
    useEffect(() => clearScreenTrail, [])
    return null
}
