import { type ReactElement } from 'react'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@winterop-com/sokkel-ui/primitives/dropdown-menu'
import type { EdgeRouting, LayoutChoice, LayoutDirection, LayoutSpacing } from '@/lib/dag-layout'
import { LABELS } from '@/lib/labels'

const WORDS = LABELS.shell.layout

const DIRECTIONS: readonly [LayoutDirection, string][] = [
    ['right', WORDS.right],
    ['down', WORDS.down],
]
const ROUTINGS: readonly [EdgeRouting, string][] = [
    ['default', WORDS.stepped],
    ['orthogonal', WORDS.orthogonal],
    ['splines', WORDS.splines],
]
const SPACING: readonly [LayoutSpacing, string][] = [
    ['default', WORDS.normal],
    ['compact', WORDS.compact],
    ['roomy', WORDS.roomy],
]

/**
 * How a view of a graph is laid out: which way it runs, how its edges are drawn, and how much
 * room is between its boxes. The choice is the visit's and is kept nowhere.
 *
 * `trigger` is the button that opens it, which each canvas draws in its own chrome.
 */
export function LayoutMenu({
    choice,
    onChoose,
    trigger,
}: {
    choice: LayoutChoice
    onChoose: (choice: LayoutChoice) => void
    trigger: ReactElement
}) {
    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={trigger} />
            <DropdownMenuContent align="end" className="w-44">
                <Group
                    label={WORDS.direction}
                    value={choice.direction}
                    options={DIRECTIONS}
                    onChoose={(direction) => {
                        onChoose({ ...choice, direction })
                    }}
                />
                <DropdownMenuSeparator />
                <Group
                    label={WORDS.edges}
                    value={choice.routing}
                    options={ROUTINGS}
                    onChoose={(routing) => {
                        onChoose({ ...choice, routing })
                    }}
                />
                <DropdownMenuSeparator />
                <Group
                    label={WORDS.spacing}
                    value={choice.spacing}
                    options={SPACING}
                    onChoose={(spacing) => {
                        onChoose({ ...choice, spacing })
                    }}
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

function Group<T extends string>({
    label,
    value,
    options,
    onChoose,
}: {
    label: string
    value: T
    options: readonly [T, string][]
    onChoose: (value: T) => void
}) {
    return (
        <DropdownMenuGroup>
            <DropdownMenuLabel>{label}</DropdownMenuLabel>
            <DropdownMenuRadioGroup
                value={value}
                onValueChange={(next) => {
                    onChoose(next as T)
                }}
            >
                {options.map(([option, word]) => (
                    <DropdownMenuRadioItem key={option} value={option} closeOnClick>
                        {word}
                    </DropdownMenuRadioItem>
                ))}
            </DropdownMenuRadioGroup>
        </DropdownMenuGroup>
    )
}
