import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'

import { SignIn, type SignInValues } from '@winterop-com/sokkel-ui/SignIn'
import { FlowLines } from '@winterop-com/sokkel-ui/SignInArt'
import { useStore } from '@/hooks/use-store'
import { appConfig } from '@/lib/api'
import { authStore, refreshIdentity, signIn } from '@/lib/auth'
import { SIGN_IN_WORDS } from '@/lib/design-system'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { DASHBOARD_PATH } from '@/lib/nav'
import { said } from '@/lib/refusal'

/** Where this browser keeps the username it last signed in as. */
const USERNAME_STORAGE_KEY = 'dirigent.username'

/** Where this browser keeps the width the brand pane was dragged to. */
const PANE_STORAGE_KEY = 'dirigent.login.pane'

/**
 * The login screen, sokkel-ui's `SignIn` outside the shell.
 *
 * The brand pane carries the rail's mark, the wordmark, and the host and version this instance
 * answered with: `/config.json` is unauthenticated, so the version is known before anybody signs
 * in, and a read that fails leaves the host alone. The refusal is the server's own sentence.
 */
export function Login() {
    const auth = useStore(authStore)
    const navigate = useNavigate()
    const [version, setVersion] = useState<string | null>(null)

    // A reader already signed in -- a bookmark, a back button -- is sent on rather than shown a form.
    const signedIn = auth.status === 'signed-in'
    useEffect(() => {
        if (signedIn) void navigate(DASHBOARD_PATH, { replace: true })
    }, [navigate, signedIn])

    // A form sent before an `unknown` status resolved would sign in over a session that was good.
    useEffect(() => {
        if (auth.status === 'unknown') void refreshIdentity().catch(() => undefined)
    }, [auth.status])

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

    async function submit(values: SignInValues): Promise<void> {
        if (await signIn(values.user, values.password)) void navigate(DASHBOARD_PATH, { replace: true })
    }

    return (
        <SignIn
            mark={<ICONS.brand aria-hidden />}
            name={LABELS.login.wordmark}
            art={<FlowLines />}
            facts={[
                { label: LABELS.login.instance, value: window.location.host },
                { label: LABELS.word.version.term, value: version ?? '' },
            ]}
            resizable
            widthKey={PANE_STORAGE_KEY}
            eyebrow={LABELS.login.eyebrow}
            description={LABELS.login.subtitle}
            rememberKey={USERNAME_STORAGE_KEY}
            error={auth.problem === null ? undefined : said(auth.problem)}
            busy={auth.working}
            onSubmit={(values) => {
                void submit(values)
            }}
            words={SIGN_IN_WORDS}
        />
    )
}
