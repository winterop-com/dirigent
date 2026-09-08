import { Link } from 'react-router'

import { Card, CardContent } from '@/components/ui/card'
import type { Tile, TileTone } from '@/lib/overview'

/** How each tone is inked: the four semantic aliases, and the absence of one. */
const TONES: Record<TileTone, string> = {
    neutral: 'text-foreground',
    good: 'text-good',
    info: 'text-info',
    warning: 'text-warning',
    critical: 'text-critical',
}

/**
 * One number, the sentence under it, and the screen it stands for.
 *
 * THE SENTENCE IS CLAMPED, AND THE WHOLE OF IT IS THE TITLE. A note carries what an external
 * system said when it refused, which is a sentence of no length this app decides, and a row of
 * tiles is one grid row -- so one connection with a long refusal on it grows all of them. Two
 * lines is what every note this app writes itself fits in.
 */
export function TileCard({ tile }: { tile: Tile }) {
    return (
        <Card className="hover:bg-accent/40 p-0 transition-colors">
            <CardContent className="p-0">
                <Link to={tile.to} className="block space-y-1 p-3 outline-none focus-visible:underline">
                    <p className="text-muted-foreground text-xs">{tile.label}</p>
                    <p className={`text-base font-semibold ${TONES[tile.tone]}`}>{tile.value}</p>
                    <p className="text-muted-foreground line-clamp-2 text-xs" title={tile.note}>
                        {tile.note}
                    </p>
                </Link>
            </CardContent>
        </Card>
    )
}

/**
 * One number at display size, what it counts above it, and the rows it counted below.
 *
 * THE NUMBER WEARS THE ONE NAMED SIZE OUTSIDE THE TYPE SCALE. `text-stat` is declared once in
 * index.css and spent here alone; it is a class rather than a composition because
 * `tailwind-merge` reads any other `text-` class as a colour and would drop it.
 *
 * THE NOTE IS OPTIONAL AND THE HEIGHT IS NOT. Most of these tiles have nothing to add to their
 * own label, so the note is drawn only where there is one -- and the row stretches every card to
 * the tallest, so a tile that says nothing still lines up with the ones that do.
 */
export function StatTile({ tile }: { tile: Tile }) {
    return (
        <Card className="hover:bg-accent/40 h-full p-0 transition-colors">
            <CardContent className="p-0">
                <Link to={tile.to} className="block space-y-0.5 p-3 outline-none focus-visible:underline">
                    <p className="text-muted-foreground text-xs">{tile.label}</p>
                    <p className={`text-stat ${TONES[tile.tone]}`}>{tile.value}</p>
                    {tile.note !== '' && (
                        <p className="text-muted-foreground truncate text-xs" title={tile.note}>
                            {tile.note}
                        </p>
                    )}
                </Link>
            </CardContent>
        </Card>
    )
}

/** A tile whose read has not landed, holding its space so the row does not jump under a reader. */
export function TilePlaceholder() {
    return (
        <Card className="h-full">
            <CardContent className="text-faint p-3 text-xs">Reading</CardContent>
        </Card>
    )
}
