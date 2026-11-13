import { Chip } from '@winterop-com/sokkel-ui/Chip'

import { kindFamily, kindLabel } from '@/lib/kinds'

/**
 * One kind, drawn the one way this app draws a kind.
 *
 * The chip is sokkel-ui's, worn in the hue of the family `lib/kinds` puts the kind in, so a
 * connection kind in a listing row and the same kind in a panel cannot drift apart. Nothing here
 * decides a color.
 */
export function KindChip({ kind, className }: { kind: string; className?: string }) {
    return (
        <Chip hue={kindFamily(kind)} className={className}>
            {kindLabel(kind)}
        </Chip>
    )
}
