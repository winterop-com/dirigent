import { ArrowRight, CircleAlert, Eye, EyeOff, Lock, User } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { useNavigate } from 'react-router'

import { BrandPane } from '@/components/login/BrandPane'
import { clampPaneWidth, rememberPaneWidth, rememberedPaneWidth } from '@/components/login/pane-width'
import { rememberUsername, rememberedUsername } from '@/components/login/remembered'
import { SeamHandle } from '@/components/login/SeamHandle'
import { revealOf } from '@/components/login/reveal'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useStore } from '@/hooks/use-store'
import { appConfig } from '@/lib/api'
import { authStore, refreshIdentity, signIn } from '@/lib/auth'
import { DASHBOARD_PATH } from '@/lib/nav'

export const SIGN_IN_LABEL = 'Sign in'
export const USERNAME_LABEL = 'Username'
export const PASSWORD_LABEL = 'Password'

/** What the button's tooltip says while it will not take a second submit. */
export const WORKING_TITLE = 'Signing in'

/** The field treatment this screen alone wears: taller than a control, and edged in every palette. */
const FIELD = 'border-border-strong h-12 rounded-lg pl-11'

/**
 * The login screen.
 *
 * OUTSIDE THE SHELL, deliberately: there is no navigation to draw for somebody who cannot reach
 * any of it, and a rail behind a login form offers screens that will refuse them.
 *
 * TWO PANES, BECAUSE THE DOOR HAS TWO JOBS. The brand pane says which instance this is -- the
 * mark the rail wears, the wordmark, the host and the version it answered with -- and the form
 * pane asks the one question. Below lg the panes stack, brand first and compact, because the
 * answer to "what am I signing into" is read before the fields either way -- and because two
 * columns in a window under 1024px would draw the pane narrower than its own floor.
 *
 * THE DOOR GREETS, AND NOTHING BEHIND IT DOES. This is the one screen a person meets before the
 * product's own facts are on it, so it carries an eyebrow, a heading, a one-line subtitle and
 * placeholders -- see docs/ui-conventions.md, which says the same and says no other screen may
 * copy any of it.
 *
 * THE SEAM IS DRAGGED, AND WHAT IS STORED IS PIXELS, like every other edge in this app. A
 * width somebody chose is that browser's from then on, held between the same bounds the pane's
 * own clamp has; the clamp rules again the moment the choice is cleared.
 *
 * THE REFUSAL IS THE SERVER'S OWN SENTENCE. A wrong password and a rate limit are different
 * things and the server says which; restating either as "login failed" would throw away the one
 * fact worth having -- that this instance will accept nothing for a minute.
 *
 * AND IT TAKES NO ROOM. The form is centred in its column, so a notice that took space would
 * move every field and the button the moment somebody got a password wrong. It hangs below the
 * button, positioned out of the flow, and the form stays exactly where it was.
 */
export function Login() {
    const auth = useStore(authStore)
    const navigate = useNavigate()
    const [username, setUsername] = useState(rememberedUsername)
    const [password, setPassword] = useState('')
    const [shown, setShown] = useState(false)
    const [version, setVersion] = useState<string | null>(null)
    const reveal = revealOf(shown)
    const pane = useRef<HTMLElement>(null)
    const [chosen, setChosen] = useState<number | null>(() => {
        const stored = rememberedPaneWidth()
        return stored === null ? null : clampPaneWidth(stored, window.innerWidth)
    })
    // What the pane is actually drawn at, which is the clamp's answer until somebody chooses.
    const [drawn, setDrawn] = useState(0)

    // A reader who is already signed in and lands here -- a bookmark, a back button -- is sent on
    // rather than shown a form for a session they already hold.
    const signedIn = auth.status === 'signed-in'
    useEffect(() => {
        if (signedIn) void navigate(DASHBOARD_PATH, { replace: true })
    }, [navigate, signedIn])

    // The status may still be `unknown` when this screen is reached directly, and a form that
    // submitted before that resolved would sign in over a session that was already good.
    useEffect(() => {
        if (auth.status === 'unknown') void refreshIdentity().catch(() => undefined)
    }, [auth.status])

    // The seam is dragged in pixels, so the width it starts from is the one on screen rather
    // than the one that was chosen -- there may not have been one.
    useLayoutEffect(() => {
        const element = pane.current
        if (element === null) return
        const observer = new ResizeObserver((entries) => {
            setDrawn(entries[0].contentRect.width)
        })
        observer.observe(element)
        return () => {
            observer.disconnect()
        }
    }, [])

    // A window that narrows past what the two columns need holds the choice inside the new
    // bounds rather than throwing it away: the intent comes back with the window.
    useEffect(() => {
        if (chosen === null) return
        function onResize(): void {
            setChosen((held) => (held === null ? null : clampPaneWidth(held, window.innerWidth)))
        }
        window.addEventListener('resize', onResize)
        return () => {
            window.removeEventListener('resize', onResize)
        }
    }, [chosen])

    // `/config.json` is unauthenticated, so the pane can state the version before anybody signs
    // in. A read that fails leaves the pane saying the host and nothing else.
    useEffect(() => {
        let live = true
        void appConfig().then(
            (config) => {
                if (live) setVersion(config.version)
            },
            () => undefined,
        )
        return () => {
            live = false
        }
    }, [])

    function choose(width: number): void {
        setChosen(width)
        rememberPaneWidth(width)
    }

    function forget(): void {
        setChosen(null)
        rememberPaneWidth(null)
    }

    async function submit(event: FormEvent): Promise<void> {
        event.preventDefault()
        if (await signIn(username, password)) {
            setPassword('')
            setShown(false)
            rememberUsername(username)
            void navigate(DASHBOARD_PATH, { replace: true })
        }
    }

    return (
        // The brand pane is 52% of the reference width and bounded: never narrower than 560px,
        // never wider than 1056px, the width at which the graph reaches its largest scale, so
        // past it a wide display gives its extra room to the form pane. Between lg and xl it
        // holds its floor and the form column takes what is left, which at lg is still the
        // form and its padding; below lg the two stack and the pane is a strip.
        <div
            className="flex min-h-svh flex-col bg-background lg:grid lg:grid-cols-[var(--login-pane,minmax(35rem,45%))_1fr] xl:grid-cols-[var(--login-pane,clamp(35rem,52vw,66rem))_1fr]"
            style={chosen === null ? undefined : ({ '--login-pane': `${String(chosen)}px` } as CSSProperties)}
        >
            <BrandPane version={version} ref={pane} />
            {/* The form pane is the lit surface in the dark palette: against a brand pane that is
                dark in both, a form on the page ground would be one rung from it and the seam
                between the two would not be there at all. The form is centred in it at every
                width, so what a wider window gives this column is spent evenly either side of
                the one question it asks. */}
            <main className="relative flex flex-1 items-center justify-center p-6 lg:p-12 dark:bg-card">
                <SeamHandle width={drawn} onChange={choose} onReset={forget} />
                <form
                    className="relative grid w-full max-w-xs gap-5 xl:w-[26.875rem] xl:max-w-none"
                    onSubmit={(event) => {
                        void submit(event)
                    }}
                >
                    <div className="grid gap-2">
                        <p className="text-sm tracking-[0.18em] text-primary-ink uppercase">
                            Welcome to dirigent
                        </p>
                        <h2 className="text-display font-semibold tracking-tight">{SIGN_IN_LABEL}</h2>
                        <p className="text-sm text-muted-foreground">Enter your credentials to continue.</p>
                    </div>
                    <div className="grid gap-1.5">
                        <Label htmlFor="username">{USERNAME_LABEL}</Label>
                        <div className="relative">
                            <User
                                className="pointer-events-none absolute top-1/2 left-4 size-4.5 -translate-y-1/2 text-muted-foreground"
                                aria-hidden
                            />
                            <Input
                                id="username"
                                name="username"
                                autoComplete="username"
                                autoFocus
                                required
                                placeholder="Your username"
                                className={FIELD}
                                value={username}
                                onChange={(event) => {
                                    setUsername(event.target.value)
                                }}
                            />
                        </div>
                    </div>
                    <div className="grid gap-1.5">
                        <Label htmlFor="password">{PASSWORD_LABEL}</Label>
                        <div className="relative">
                            <Lock
                                className="pointer-events-none absolute top-1/2 left-4 size-4.5 -translate-y-1/2 text-muted-foreground"
                                aria-hidden
                            />
                            <Input
                                id="password"
                                name="password"
                                type={reveal.inputType}
                                autoComplete="current-password"
                                required
                                placeholder="Your password"
                                className={`${FIELD} pr-12`}
                                value={password}
                                onChange={(event) => {
                                    setPassword(event.target.value)
                                }}
                            />
                            <button
                                type="button"
                                aria-label={reveal.label}
                                aria-pressed={shown}
                                onClick={() => {
                                    setShown(!shown)
                                }}
                                className="absolute top-1/2 right-3 -translate-y-1/2 rounded-md p-1 text-muted-foreground outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50"
                            >
                                {shown ? (
                                    <EyeOff className="size-4.5" aria-hidden />
                                ) : (
                                    <Eye className="size-4.5" aria-hidden />
                                )}
                            </button>
                        </div>
                    </div>
                    <Button
                        type="submit"
                        className="h-13 w-full rounded-lg"
                        disabled={auth.working}
                        title={auth.working ? WORKING_TITLE : undefined}
                    >
                        {SIGN_IN_LABEL}
                        <ArrowRight className="size-4.5" aria-hidden />
                    </Button>
                    {auth.problem !== null && (
                        <p
                            role="alert"
                            className="absolute inset-x-0 top-[calc(100%+1.5rem)] flex h-12 items-center gap-3 rounded-lg border border-critical/40 bg-critical/10 px-4 text-sm text-critical"
                        >
                            <CircleAlert className="size-4 shrink-0" aria-hidden />
                            <span className="truncate">{auth.problem.detail}</span>
                        </p>
                    )}
                </form>
            </main>
        </div>
    )
}
