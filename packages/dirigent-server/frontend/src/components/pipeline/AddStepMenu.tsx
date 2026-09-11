import { ControlButton } from '@xyflow/react'
import { Plus } from 'lucide-react'
import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

import { KindChip } from '@/components/KindChip'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { blockShelves, searchBlocks, type BlockCrumb } from '@/lib/add-step'
import type { BlockEntry } from '@/lib/blocks'
import { cn } from '@/lib/utils'

/**
 * The one menu every add-step gesture opens: the right-click on the canvas, the button in its
 * corner, and a connection let go over empty ground.
 *
 * ONE MENU, THREE ANCHORS. What is being asked is the same question wherever it was asked
 * from -- which block -- so the rows are written once and only what the menu hangs off differs:
 * the pointer, the button, or the point a connection was dropped at.
 *
 * A BLOCK IS FOUND TWO WAYS. The groups are the shelving the catalog already has, for
 * somebody who knows where a block lives; the box is for somebody who knows what it is called.
 * Typing replaces the shelves with flat results because a breadcrumb is faster to read than a
 * tree is to walk, and clearing the box puts the shelves back.
 *
 * THE BOX HOLDS THE KEYS WHILE IT HOLDS TEXT. A menu answers arrows and letters itself, which
 * would take a keystroke meant for the search box, so while there is something in it this
 * component moves through the results and the menu is told nothing. An empty box hands the
 * arrows back, and the rows are a menu again.
 */

export const ADD_STEP_LABEL = 'Add step'

/** What the search box narrows, in the words of what it searches. */
const SEARCH_LABEL = 'Search blocks by id, summary or kind'

/**
 * The menu, hung off the button in the canvas's corner.
 *
 * THE ONE ADD-STEP GESTURE THAT CAN BE SEEN. A right-click has to be known about and a palette
 * command has to be remembered; this is the control a reader who has never opened this screen
 * before can find, and it is why the empty canvas states the fact rather than narrating a
 * gesture. It is a real button in the control cluster, so it takes the focus ring and opens on
 * Enter or Space like every other menu in the app, and the popup is anchored to it rather than
 * to a point -- which is what keeps the menu inside the viewport with no arithmetic here.
 */
export function AddStepButton({
    blocks,
    onChoose,
}: {
    blocks: BlockEntry[]
    onChoose: (block: string) => void
}) {
    const [open, setOpen] = useState(false)

    return (
        <DropdownMenu open={open} onOpenChange={setOpen}>
            <DropdownMenuTrigger
                render={
                    <ControlButton title={ADD_STEP_LABEL} aria-label={ADD_STEP_LABEL}>
                        <Plus />
                    </ControlButton>
                }
            />
            {open && (
                <AddStepMenuContent
                    blocks={blocks}
                    after={null}
                    onChoose={onChoose}
                    onClose={() => {
                        setOpen(false)
                    }}
                />
            )}
        </DropdownMenu>
    )
}

/**
 * The menu, hung off a point on the screen.
 *
 * The anchor is an element of no size at that point, because what a menu is placed against is
 * an element: it is what keeps the popup inside the viewport and flips a submenu that would not
 * fit, which a menu positioned by hand would each have to decide for itself.
 */
export function AddStepMenuAt({
    blocks,
    at,
    after = null,
    onChoose,
    onClose,
}: {
    blocks: BlockEntry[]
    /** Where the menu opens, in viewport coordinates. */
    at: { x: number; y: number }
    /** The step the new one will wait for, when it was drawn out of one. */
    after?: string | null
    onChoose: (block: string) => void
    onClose: () => void
}) {
    return (
        <DropdownMenu
            open
            onOpenChange={(next) => {
                if (!next) onClose()
            }}
        >
            <DropdownMenuTrigger
                aria-label={ADD_STEP_LABEL}
                tabIndex={-1}
                className="pointer-events-none fixed size-0"
                style={{ left: at.x, top: at.y }}
            />
            <AddStepMenuContent blocks={blocks} after={after} onChoose={onChoose} onClose={onClose} />
        </DropdownMenu>
    )
}

function AddStepMenuContent({
    blocks,
    after,
    onChoose,
    onClose,
}: {
    blocks: BlockEntry[]
    after: string | null
    onChoose: (block: string) => void
    onClose: () => void
}) {
    const [needle, setNeedle] = useState('')
    const [active, setActive] = useState(0)
    const box = useRef<HTMLInputElement | null>(null)
    const shelves = useMemo(() => blockShelves(blocks), [blocks])
    const found = useMemo(() => searchBlocks(blocks, needle), [blocks, needle])
    const searching = needle.trim() !== ''

    useEffect(() => {
        // The popup takes the focus as it opens, and the box is where the next keystroke belongs.
        const frame = requestAnimationFrame(() => {
            box.current?.focus()
        })
        return () => {
            cancelAnimationFrame(frame)
        }
    }, [])

    const choose = (block: string) => {
        onChoose(block)
        onClose()
    }

    const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
        if (event.key === 'Tab') return
        if (event.key === 'Escape') {
            // The first one clears what was typed; the menu itself answers the second.
            if (needle === '') return
            setNeedle('')
            setActive(0)
            event.preventDefault()
            event.stopPropagation()
            return
        }
        if (needle === '') {
            // Nothing typed: the rows below are a menu, and the arrows are the menu's own.
            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') event.stopPropagation()
            return
        }
        event.stopPropagation()
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            if (found.length === 0) return
            const step = event.key === 'ArrowDown' ? 1 : found.length - 1
            setActive((at) => (at + step) % found.length)
            return
        }
        if (event.key === 'Enter') {
            event.preventDefault()
            const chosen = found[active]
            if (chosen !== undefined) choose(chosen.entry.id)
        }
    }

    return (
        <DropdownMenuContent className="w-80 p-0" align="start">
            <div className="sticky top-0 z-10 flex flex-col gap-1.5 bg-popover p-2">
                <p className="text-xs font-semibold tracking-wide text-faint uppercase">
                    {after === null ? ADD_STEP_LABEL : `${ADD_STEP_LABEL} after ${after}`}
                </p>
                <Input
                    ref={box}
                    value={needle}
                    autoFocus
                    spellCheck={false}
                    placeholder="Search"
                    aria-label={SEARCH_LABEL}
                    onKeyDown={onKeyDown}
                    onChange={(event) => {
                        setNeedle(event.target.value)
                        setActive(0)
                    }}
                />
            </div>

            <div className="p-1 pt-0">
                {searching ? (
                    <Results found={found} active={active} onChoose={choose} />
                ) : (
                    // Every group is a group, one block or many: a uniform root reads as one
                    // arrangement, and a lone block behind its shelf is still where it files.
                    shelves.map((shelf) => (
                        <Fragment key={shelf.shelf}>
                            <DropdownMenuSub>
                                <DropdownMenuSubTrigger className="font-mono">
                                    {shelf.shelf}
                                </DropdownMenuSubTrigger>
                                <DropdownMenuSubContent className="w-72">
                                    {shelf.blocks.map((entry) => (
                                        <BlockRow key={entry.id} entry={entry} onChoose={choose}>
                                            <span className="font-mono text-sm font-semibold">
                                                {entry.id}
                                            </span>
                                        </BlockRow>
                                    ))}
                                </DropdownMenuSubContent>
                            </DropdownMenuSub>
                        </Fragment>
                    ))
                )}
            </div>
        </DropdownMenuContent>
    )
}

/** What the box found, breadcrumbed, with the one this app's own arrows are on marked. */
function Results({
    found,
    active,
    onChoose,
}: {
    found: BlockCrumb[]
    active: number
    onChoose: (block: string) => void
}) {
    if (found.length === 0) {
        return <p className="px-1.5 py-2 text-sm text-muted-foreground">No block matches that.</p>
    }
    return (
        <>
            {found.map((crumb, index) => (
                <BlockRow
                    key={crumb.entry.id}
                    entry={crumb.entry}
                    active={index === active}
                    onChoose={onChoose}
                >
                    <span className="font-mono text-sm">
                        <span className="text-muted-foreground">{crumb.family}</span>
                        <span className="text-faint"> ▸ </span>
                        <span className="font-semibold">{crumb.rest}</span>
                    </span>
                </BlockRow>
            ))}
        </>
    )
}

/**
 * One block to add: what it is called, and what it says about itself.
 *
 * ONLY A SENSOR WEARS A CHIP. Which block waits for something is the one thing a shelf cannot
 * say, and it is the minority answer; a chip on every row would say what the absence of one
 * already says, and six identical `operator` chips down a shelf are noise rather than a
 * vocabulary.
 */
function BlockRow({
    entry,
    active = false,
    onChoose,
    children,
}: {
    entry: BlockEntry
    active?: boolean
    onChoose: (block: string) => void
    children: ReactNode
}) {
    return (
        <DropdownMenuItem
            className={cn('flex-col items-start gap-0.5', active && 'bg-accent text-accent-foreground')}
            data-active={active || undefined}
            onClick={() => {
                onChoose(entry.id)
            }}
        >
            <span className="flex w-full items-center gap-2">
                {children}
                {entry.kind === 'sensor' && <KindChip kind={entry.kind} className="ml-auto" />}
            </span>
            <span className="text-xs text-muted-foreground">{entry.summary}</span>
        </DropdownMenuItem>
    )
}
