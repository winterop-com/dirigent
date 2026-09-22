import { ChevronRight } from 'lucide-react'
import { useState, type CSSProperties } from 'react'
import { Link } from 'react-router'

import { Mark } from '@/components/Mark'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useSmallScreen } from '@/hooks/use-small-screen'
import { channelCode, channelLink, channelView, type Channel, type ChannelView } from '@/lib/alerting'
import { formatRelative } from '@/lib/format'
import { kindGlyph } from '@/lib/glyphs'
import { cn } from '@/lib/utils'

/** What each dot is painted in, named through the semantic aliases rather than a colour. */
const TONES: Record<ChannelView['tone'], string> = {
    good: 'var(--good)',
    critical: 'var(--critical)',
    quiet: 'var(--faint)',
}

/** The chip: a glyph, a code and a dot, at the height a pointer and a finger both want. */
const CHIP =
    'flex min-h-9 items-center gap-2 rounded-full border border-border bg-card py-1 pr-3 pl-2.5 transition-colors'

/** What a control this app draws wears when a pointer or the keyboard reaches it. */
const REACHED =
    'hover:bg-muted focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none'

/**
 * The channels an alert can leave by, and what each one last proved about itself.
 *
 * A CHANNEL THAT QUIETLY STOPPED IS THE THING THIS STRIP EXISTS FOR. The rules below say what
 * would be sent; this says whether there is anywhere for it to go. The reading is the
 * connection's own last health check -- the same one `dg connection check` writes -- so nothing
 * here decides whether a channel is well, it only says when that was last asked.
 *
 * ONE LINE OF CHIPS, AND A FOLD ON A PHONE. A chip is a glyph, a code and a dot; everything else
 * it knows is in the tooltip, so a strip of twelve channels is still one line to read. Below the
 * breakpoint the heading itself becomes the fold, wearing one dot per channel, because a screen
 * that opens on a table of channels is a screen whose rules are below the fold.
 */
export function ChannelStrip({ channels, read }: { channels: readonly Channel[]; read: boolean }) {
    const small = useSmallScreen()
    const note = channelNote(channels.length, read)
    if (small) return <ChannelFold channels={channels} note={note} />
    return (
        <>
            <h2 className="text-sm font-semibold">Channels</h2>
            {note === null ? (
                <ul className="flex flex-wrap gap-2">
                    {channels.map((channel) => (
                        <li key={channel.id} className="flex">
                            <ChannelChip channel={channel} />
                        </li>
                    ))}
                </ul>
            ) : (
                <p className={note.tone}>{note.text}</p>
            )}
        </>
    )
}

/** What the section says instead of channels, and nothing where it has some to draw. */
function channelNote(count: number, read: boolean): { text: string; tone: string } | null {
    if (!read) return { text: 'Reading from the server', tone: 'text-sm text-faint' }
    if (count === 0) return { text: 'No channel is installed.', tone: 'text-sm text-muted-foreground' }
    return null
}

/**
 * One channel, at a glance: what kind it is, which credential it is, and whether it delivers.
 *
 * THE CHIP HOLDS THREE THINGS AND THE TOOLTIP HOLDS THE REST. A state word, a time and a check's
 * sentence on every chip is a paragraph per channel; the dot answers the question the strip is
 * read for, and reaching a chip answers the next.
 *
 * EVERY CHIP ANSWERS A POINTER THE SAME WAY, the log channel's included. It is a button rather
 * than a link, because there is nothing behind it to open, and it wears the wash and the ring
 * its neighbours wear -- a chip drawn inert beside them would be saying it is a different kind
 * of thing.
 */
function ChannelChip({ channel }: { channel: Channel }) {
    const view = channelView(channel)
    const to = channelLink(channel)
    const body = (
        <>
            <Mark glyph={kindGlyph(channel.notifier)} />
            <span className="truncate font-mono text-xs font-semibold">{channelCode(channel)}</span>
            <Dot tone={view.tone} />
        </>
    )
    // The chip is the control itself rather than a control wrapped around one, so the ring lands
    // on what has the focus.
    const chip =
        to === null ? (
            <button type="button" className={cn(CHIP, REACHED)}>
                {body}
            </button>
        ) : (
            <Link to={to} className={cn(CHIP, REACHED)}>
                {body}
            </Link>
        )
    return (
        <Tooltip>
            <TooltipTrigger render={chip} />
            <TooltipContent className="flex-col items-start gap-1" side="bottom">
                <ChannelFacts channel={channel} view={view} />
            </TooltipContent>
        </Tooltip>
    )
}

/** What the chip does not say: the kind in words, the state, when it was proved, and by what. */
function ChannelFacts({ channel, view }: { channel: Channel; view: ChannelView }) {
    return (
        <>
            <span className="font-medium">
                {channel.notifier} · {view.label}
                {channel.last_check_at !== null && (
                    <span className="font-normal opacity-70"> {formatRelative(channel.last_check_at)}</span>
                )}
            </span>
            {channel.connection !== null && <span className="font-mono">{channel.connection}</span>}
            {view.detail !== null && <span className="opacity-70">{view.detail}</span>}
        </>
    )
}

/**
 * The strip on a phone: the heading is the fold, and it wears the answer.
 *
 * FOLDED ON EVERY VISIT. What a phone is here for is the rules and the queue; the dots say
 * whether anything about the channels wants opening, and nothing else about them is worth a
 * screenful before somebody asks for it.
 */
function ChannelFold({
    channels,
    note,
}: {
    channels: readonly Channel[]
    note: { text: string; tone: string } | null
}) {
    const [open, setOpen] = useState(false)
    return (
        <>
            <button
                type="button"
                aria-expanded={open}
                onClick={() => {
                    setOpen(!open)
                }}
                className={cn(
                    'flex min-h-finger w-full items-center gap-2.5 border-b border-border px-1 text-left',
                    REACHED,
                )}
            >
                <ChevronRight
                    className={cn('size-4 shrink-0 text-muted-foreground', open && 'rotate-90')}
                    aria-hidden
                />
                <span className="text-sm font-semibold">Channels</span>
                <span className="ml-auto flex items-center gap-1.5" aria-hidden>
                    {channels.map((channel) => (
                        <Dot key={channel.id} tone={channelView(channel).tone} />
                    ))}
                </span>
            </button>
            {open &&
                (note === null ? (
                    <table className="w-full text-sm">
                        <tbody>
                            {channels.map((channel) => (
                                <ChannelRow key={channel.id} channel={channel} />
                            ))}
                        </tbody>
                    </table>
                ) : (
                    <p className={note.tone}>{note.text}</p>
                ))}
        </>
    )
}

/** One channel opened out: the dot, what it is, and either the way in or when it was proved. */
function ChannelRow({ channel }: { channel: Channel }) {
    const view = channelView(channel)
    const to = channelLink(channel)
    const named = (
        <span className="flex items-center gap-2.5">
            <Mark glyph={kindGlyph(channel.notifier)} />
            <span className="truncate font-mono text-xs font-semibold">{channelCode(channel)}</span>
        </span>
    )
    return (
        <tr className="border-b border-border last:border-b-0">
            <td className="w-0 py-2 pr-2 align-middle">
                <Dot tone={view.tone} />
            </td>
            <td className="min-w-0 py-2 align-middle">
                {channel.connection === null || to === null ? (
                    named
                ) : (
                    <Link to={to} className={cn('control-link flex items-center rounded-md px-1', REACHED)}>
                        {named}
                    </Link>
                )}
            </td>
            <td className="w-0 py-2 pl-2 text-right align-middle whitespace-nowrap">
                {view.label === 'not set up' && to !== null ? (
                    <Link
                        to={to}
                        className={cn(
                            'control-link inline-flex items-center rounded-md text-xs text-primary-ink',
                            REACHED,
                        )}
                    >
                        Set up {channel.notifier}
                    </Link>
                ) : (
                    channel.last_check_at !== null && (
                        <span className="text-xs text-faint">{formatRelative(channel.last_check_at)}</span>
                    )
                )}
            </td>
        </tr>
    )
}

/** The dot, which says one of three things and never which kind the channel is. */
function Dot({ tone }: { tone: ChannelView['tone'] }) {
    return <span className="status-dot" style={{ '--chip': TONES[tone] } as CSSProperties} />
}
