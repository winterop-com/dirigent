/**
 * The navigation, as data.
 *
 * ONE ARRAY, READ BY THREE THINGS: the rail draws it, the command palette offers every entry as
 * a row, and the router's own table is checked against it. Adding a screen is a route plus an
 * entry here, and nothing else has to learn that the screen exists.
 *
 * THE ADMIN SECTION IS ROLE-GATED, AND THAT IS A COURTESY. The server refuses what an account
 * may not do; hiding the section means nobody is offered a screen that will refuse them.
 * Nothing here is a security boundary, and a reader who types the address still reaches the
 * page and is told by the server what it thinks of them.
 */

import {
    Bell,
    Blocks,
    BookOpen,
    CalendarClock,
    Cpu,
    FileJson,
    House,
    Play,
    Plug,
    Users,
    Workflow,
    type LucideIcon,
} from 'lucide-react'

import type { UserRole } from '@/lib/auth'
import { LABELS } from '@/lib/labels'

/** One entry in the rail: where it goes, what it is called, and the mark beside it. */
export interface NavEntry {
    /** The route path, exactly as the router spells it. */
    path: string
    label: string
    /**
     * The line the command palette carries beside the row, saying what the screen holds.
     *
     * A FRAGMENT, NOT A SENTENCE. It sits on one row of a list being searched, so it takes no
     * full stop and no verb it can do without: what is under Runs is every execution, newest
     * first. The rail does not draw it -- a label that names one of the things this app is
     * made of needs no gloss under it.
     */
    hint: string
    icon: LucideIcon
}

/** A run of entries under one heading. */
export interface NavSection {
    id: string
    /** The heading, or null for the first section, which needs none. */
    label: string | null
    /** The role an account needs before this section is offered at all. */
    requires: UserRole | null
    entries: NavEntry[]
}

/** Where a reader lands with no address of their own, which is a screen rather than a noun. */
export const DASHBOARD_PATH = '/'

/** The login screen, which is where a refused request sends a reader. */
export const LOGIN_PATH = '/login'

/**
 * The editor with no pipeline behind it, which is where a new document is written.
 *
 * It is not a rail entry: writing a pipeline is something done from the listing rather than a
 * screen somebody navigates to and leaves open.
 */
export const NEW_PIPELINE_PATH = '/pipelines/$new'

/** The design system's gallery: offered by the palette, never by the rail. */
export const DESIGN_PATH = '/design'

export const NAV: NavSection[] = [
    {
        id: 'dashboard',
        label: null,
        requires: null,
        entries: [
            {
                path: DASHBOARD_PATH,
                label: LABELS.screen.dashboard.name,
                hint: LABELS.screen.dashboard.hint,
                icon: House,
            },
        ],
    },
    {
        id: 'operate',
        label: LABELS.screen.operate,
        requires: null,
        entries: [
            {
                path: '/runs',
                label: LABELS.screen.runs.name,
                hint: LABELS.screen.runs.hint,
                icon: Play,
            },
            {
                path: '/triggers',
                label: LABELS.screen.triggers.name,
                hint: LABELS.screen.triggers.hint,
                icon: CalendarClock,
            },
        ],
    },
    {
        id: 'build',
        label: LABELS.screen.build,
        requires: null,
        entries: [
            {
                path: '/pipelines',
                label: LABELS.screen.pipelines.name,
                hint: LABELS.screen.pipelines.hint,
                icon: Workflow,
            },
            {
                path: '/connections',
                label: LABELS.screen.connections.name,
                hint: LABELS.screen.connections.hint,
                icon: Plug,
            },
            {
                path: '/schemas',
                label: LABELS.screen.schemas.name,
                hint: LABELS.screen.schemas.hint,
                icon: FileJson,
            },
        ],
    },
    {
        id: 'reference',
        label: LABELS.screen.reference,
        requires: null,
        entries: [
            {
                path: '/blocks',
                label: LABELS.screen.blocks.name,
                hint: LABELS.screen.blocks.hint,
                icon: Blocks,
            },
            {
                path: '/examples',
                label: LABELS.screen.examples.name,
                hint: LABELS.screen.examples.hint,
                icon: BookOpen,
            },
        ],
    },
    {
        id: 'admin',
        label: LABELS.screen.admin,
        requires: 'admin',
        entries: [
            {
                path: '/admin/users',
                label: LABELS.screen.users.name,
                hint: LABELS.screen.users.hint,
                icon: Users,
            },
            {
                path: '/admin/workers',
                label: LABELS.screen.workers.name,
                hint: LABELS.screen.workers.hint,
                icon: Cpu,
            },
            {
                path: '/admin/alerting',
                label: LABELS.screen.alerting.name,
                hint: LABELS.screen.alerting.hint,
                icon: Bell,
            },
        ],
    },
]

/**
 * The sections this account is offered.
 *
 * A role of null is somebody whose identity has not been read yet, and they are offered the
 * ungated sections rather than nothing: the rail is drawn once and gains its admin section when
 * the read lands, instead of the whole navigation appearing a frame late.
 */
export function sectionsFor(role: UserRole | null): NavSection[] {
    return NAV.filter((section) => section.requires === null || section.requires === role)
}

/** Every screen an account is offered, flattened, which is what the palette shelves. */
export function entriesFor(role: UserRole | null): NavEntry[] {
    return sectionsFor(role).flatMap((section) => section.entries)
}

/**
 * Whether an entry is marked only at its own address.
 *
 * An entry with other entries beneath it -- the root, which every address is under -- would
 * otherwise be marked wherever any of them is open, and the rail would say the reader is in two
 * places.
 */
export function marksOnlyItself(path: string): boolean {
    const below = path === '/' ? '/' : `${path}/`
    return NAV.flatMap((section) => section.entries).some(
        (entry) => entry.path !== path && entry.path.startsWith(below),
    )
}

/**
 * The rail entry one address is inside, or null.
 *
 * Longest path first, because an entry may be a prefix of another address it does not own.
 */
export function entryAt(path: string): NavEntry | null {
    const candidates = NAV.flatMap((section) => section.entries)
        .filter((entry) => path === entry.path || path.startsWith(`${entry.path}/`))
        .toSorted((left, right) => right.path.length - left.path.length)
    return candidates[0] ?? null
}
