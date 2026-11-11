import { useSmallScreen } from '@/hooks/use-small-screen'
import { panelStanding } from '@/lib/panels'

/**
 * What pressing a listing's row does where a row fills the panel: open what it names, or take
 * back the one already open while the panel is standing.
 *
 * A press on the open row while the panel is down opens it again rather than clearing a tint
 * nothing is showing. Whether the panel stands is read at the press.
 */
export function useRowPress<T>(
    select: (row: T) => void,
    isOpen: (row: T) => boolean,
    close: () => void,
): (row: T) => void {
    const small = useSmallScreen()
    return (row: T) => {
        if (isOpen(row) && panelStanding(small)) close()
        else select(row)
    }
}
