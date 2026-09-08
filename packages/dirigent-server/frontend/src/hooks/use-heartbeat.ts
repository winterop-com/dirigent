import { useEffect } from 'react'

/**
 * Beat while somebody is watching.
 *
 * QUIETLY CURRENT. A screen that shows what an instance is doing right now goes stale the
 * moment it stops asking, so the beat fires every few seconds while the tab is visible --
 * and not at all while it is hidden, because a dashboard nobody can see asking anyway is
 * heat. Coming back to the tab beats immediately: what the reader returns to is the present,
 * not wherever the interval happens to be.
 *
 * The beat is a quiet re-read, never a spinner: what is on screen stays until the answer
 * lands, and a beat that fails changes nothing -- the next one asks again.
 */
export function useHeartbeat(beat: () => void, seconds: number | null): void {
    useEffect(() => {
        if (seconds === null) return
        let timer: number | undefined
        const stop = () => {
            if (timer !== undefined) {
                window.clearInterval(timer)
                timer = undefined
            }
        }
        const start = () => {
            stop()
            timer = window.setInterval(beat, seconds * 1000)
        }
        const watched = () => {
            if (document.visibilityState === 'visible') {
                beat()
                start()
            } else {
                stop()
            }
        }
        if (document.visibilityState === 'visible') start()
        document.addEventListener('visibilitychange', watched)
        return () => {
            stop()
            document.removeEventListener('visibilitychange', watched)
        }
    }, [beat, seconds])
}
