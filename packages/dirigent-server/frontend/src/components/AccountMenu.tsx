import { useNavigate } from 'react-router'

import { Chip } from '@/components/ds/Chip'
import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Kbd } from '@/components/ui/kbd'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useStore } from '@/hooks/use-store'
import { authStore, signOut } from '@/lib/auth'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { LOGIN_PATH } from '@/lib/nav'
import { identityLine, serverStatus } from '@/lib/server-status'
import { SHORTCUTS_KEY } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

/**
 * The rail's bottom-left: who is signed in, the settings, the shortcuts, the way out, and which
 * instance this is.
 *
 * The username is the account's code, and `GET /auth/me` carries no display name, so the code is
 * the title here and is drawn once.
 */
export function AccountMenu({
    collapsed = false,
    className,
    onSettings,
    onShortcuts,
}: {
    /** The rail is icons alone, so the trigger is the avatar alone. */
    collapsed?: boolean
    className?: string
    onSettings: () => void
    onShortcuts: () => void
}) {
    const identity = useStore(authStore).identity
    const status = useStore(serverStatus)
    const navigate = useNavigate()
    if (identity === null) return null
    const instance =
        status.version === null
            ? identityLine(status)
            : LABELS.shell.account.instance(identityLine(status), status.version)

    return (
        <DropdownMenu>
            <Tooltip>
                <DropdownMenuTrigger
                    render={
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="ghost"
                                    aria-label={LABELS.shell.account.label(identity.username)}
                                    className={cn(
                                        'text-xs text-muted-foreground hover:text-foreground',
                                        collapsed ? 'justify-center p-0' : 'justify-start gap-2 px-3',
                                        className,
                                    )}
                                />
                            }
                        />
                    }
                >
                    <span
                        className="flex size-5 shrink-0 items-center justify-center rounded-full bg-muted font-medium text-foreground uppercase"
                        aria-hidden
                    >
                        {identity.username.slice(0, 1)}
                    </span>
                    {!collapsed && <span className="truncate font-mono">{identity.username}</span>}
                </DropdownMenuTrigger>
                <TooltipContent side="top">{LABELS.shell.account.tooltip}</TooltipContent>
            </Tooltip>
            <DropdownMenuContent side="top" align="start" className="w-64">
                <div className="flex min-w-0 items-center gap-2 px-2 py-1.5">
                    <span className="min-w-0 truncate font-mono text-sm font-medium" title={identity.username}>
                        {identity.username}
                    </span>
                    <Chip>{identity.role}</Chip>
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={onSettings}>
                    <ICONS.settings aria-hidden />
                    {LABELS.shell.settings}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onShortcuts}>
                    <ICONS.shortcuts aria-hidden />
                    {LABELS.settings.category.shortcuts}
                    <Kbd className="ml-auto">{SHORTCUTS_KEY}</Kbd>
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    onClick={() => {
                        void signOut().then(() => navigate(LOGIN_PATH, { replace: true }))
                    }}
                >
                    <ICONS.sign_out aria-hidden />
                    {LABELS.action.sign_out}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <p className="truncate px-2 py-1.5 text-xs text-muted-foreground" title={instance}>
                    {instance}
                </p>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
