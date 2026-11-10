import { useNavigate } from 'react-router'

import { useScheme } from '@winterop-com/sokkel-ui/hooks/use-scheme'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@winterop-com/sokkel-ui/primitives/dropdown-menu'
import { Kbd } from '@winterop-com/sokkel-ui/primitives/kbd'
import { useStore } from '@/hooks/use-store'
import { authStore, signOut } from '@/lib/auth'
import { ICONS } from '@/lib/icons'
import { initialOf } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { LOGIN_PATH } from '@/lib/nav'
import { identityLine, serverStatus } from '@/lib/server-status'
import { SHORTCUTS_KEY } from '@/lib/shortcuts'
import { MODE_ICONS, MODE_LABELS, MODES, modeOf } from '@/lib/theme'
import { cn } from '@/lib/utils'

/** The round mark that stands for the account: its initial on the brand's amber. */
function Avatar({ username, large }: { username: string; large?: boolean }) {
    return (
        <span
            data-account-avatar
            className={cn(
                'flex shrink-0 items-center justify-center rounded-full bg-brand font-semibold text-brand-foreground',
                large ? 'size-8 text-sm' : 'size-6 text-xs',
            )}
            aria-hidden
        >
            {initialOf(username)}
        </span>
    )
}

/**
 * The rail's bottom-left: who is signed in, and the menu of what is theirs -- the settings, the
 * shortcuts, the appearance, the way out -- headed by which instance this is.
 *
 * The username is the account's code, and `GET /auth/me` carries no display name, so the code is
 * the title here. It is the reader's own name, so it wears the UI face rather than mono.
 */
export function AccountMenu({
    className,
    onSettings,
    onShortcuts,
}: {
    className?: string
    onSettings: () => void
    onShortcuts: () => void
}) {
    const identity = useStore(authStore).identity
    const status = useStore(serverStatus)
    const { scheme, resolved, setScheme } = useScheme()
    const navigate = useNavigate()
    if (identity === null) return null
    const instance =
        status.version === null
            ? identityLine(status)
            : LABELS.shell.account.instance(identityLine(status), status.version)
    const AppearanceIcon = resolved === 'light' ? ICONS.light : ICONS.dark

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        variant="ghost"
                        size="lg"
                        aria-label={LABELS.shell.account.label(identity.username)}
                        className={cn('justify-start gap-2.5 px-1.5 text-sm', className)}
                    />
                }
            >
                <Avatar username={identity.username} />
                <span className="min-w-0 flex-1 truncate text-left">{identity.username}</span>
                <ICONS.selector className="size-4 shrink-0 text-muted-foreground" aria-hidden />
            </DropdownMenuTrigger>
            <DropdownMenuContent side="top" align="start" className="w-64">
                <div className="flex min-w-0 items-center gap-2.5 px-2 py-1.5">
                    <Avatar username={identity.username} large />
                    <div className="flex min-w-0 flex-1 flex-col">
                        <div className="flex min-w-0 items-baseline gap-2">
                            <span className="min-w-0 truncate text-sm font-medium" title={identity.username}>
                                {identity.username}
                            </span>
                            <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                                {identity.role}
                            </span>
                        </div>
                        <span className="truncate text-xs text-muted-foreground" title={instance}>
                            {instance}
                        </span>
                    </div>
                </div>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={onSettings}>
                    <ICONS.settings aria-hidden />
                    {LABELS.shell.settings}
                </DropdownMenuItem>
                <DropdownMenuItem onClick={onShortcuts}>
                    <ICONS.shortcuts aria-hidden />
                    {LABELS.shell.account.shortcuts}
                    <Kbd className="ml-auto">{SHORTCUTS_KEY}</Kbd>
                </DropdownMenuItem>
                <DropdownMenuSub>
                    <DropdownMenuSubTrigger>
                        <AppearanceIcon aria-hidden />
                        {LABELS.shell.account.appearance}
                    </DropdownMenuSubTrigger>
                    <DropdownMenuSubContent className="w-36">
                        <DropdownMenuRadioGroup
                            value={scheme}
                            onValueChange={(mode: string) => {
                                setScheme(modeOf(mode))
                            }}
                        >
                            {MODES.map((mode) => {
                                const Icon = MODE_ICONS[mode]
                                return (
                                    <DropdownMenuRadioItem key={mode} value={mode} closeOnClick={false}>
                                        <Icon aria-hidden />
                                        {MODE_LABELS[mode]}
                                    </DropdownMenuRadioItem>
                                )
                            })}
                        </DropdownMenuRadioGroup>
                    </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    onClick={() => {
                        void signOut().then(() => navigate(LOGIN_PATH, { replace: true }))
                    }}
                >
                    <ICONS.sign_out aria-hidden />
                    {LABELS.action.sign_out}
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
