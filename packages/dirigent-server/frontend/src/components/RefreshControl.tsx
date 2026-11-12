import { SplitButton } from '@winterop-com/sokkel-ui/SplitButton'
import { useStore } from '@/hooks/use-store'
import { splitWords } from '@/lib/design-system'
import { ICONS } from '@/lib/icons'
import { REFRESH_CHOICES, refreshLabel, refreshSeconds, setRefreshSeconds } from '@/lib/refresh'
import { LABELS } from '@/lib/labels'

export const REFRESH_LABEL = LABELS.action.refresh
export const CADENCE_LABEL = LABELS.shell.cadence

/**
 * The refresh control: the verb, and how often it happens by itself.
 *
 * sokkel-ui's `SplitButton`: the face refreshes now and shows the cadence, and the chevron
 * holds the cadences as one set of choices, the one in force checked, and says on hover what it
 * chooses. The cadence is the app's, not this screen's.
 */
export function RefreshControl({ onRefresh }: { onRefresh: () => void }) {
    const seconds = useStore(refreshSeconds)
    return (
        <SplitButton
            variant="outline"
            size="sm"
            label={REFRESH_LABEL}
            title={LABELS.shell.refresh_every(refreshLabel(seconds))}
            onClick={onRefresh}
            words={splitWords(CADENCE_LABEL, CADENCE_LABEL)}
            items={REFRESH_CHOICES.map((choice) => ({
                label: refreshLabel(choice),
                checked: choice === seconds,
                onSelect: () => {
                    setRefreshSeconds(choice)
                },
            }))}
        >
            <ICONS.refresh aria-hidden />
            {REFRESH_LABEL}
            <span className="font-mono text-xs text-muted-foreground">{refreshLabel(seconds)}</span>
        </SplitButton>
    )
}
