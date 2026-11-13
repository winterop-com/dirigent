import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link as RouterLink } from 'react-router'

import { useAppearance } from '@winterop-com/sokkel-ui/hooks/use-appearance'
import { isInternalLink, LinkProvider, type RoutedLinkProps } from '@winterop-com/sokkel-ui/Link'
import { StatusProvider } from '@winterop-com/sokkel-ui/StatusProvider'

import { registerPlugins } from '@winterop-com/sokkel-ui/lib/plugins'
import { Toaster } from '@winterop-com/sokkel-ui/primitives/sonner'
import { TooltipProvider } from '@winterop-com/sokkel-ui/primitives/tooltip'

import { setElkEngine } from '@winterop-com/sokkel-ui-graph/layout'
import { fhir } from '@winterop-com/sokkel-ui-fhir/plugin'

import App from '@/App'
import { elkEngine } from '@/components/graph/elk'
import { servedByInstance } from '@/lib/docs'
import { FALLBACK, STATUSES } from '@/lib/status'
import { registerDirigentFormats } from '@/lib/schema-formats'
import { APPEARANCE_DEFAULTS, APPEARANCE_OFFER } from '@/lib/theme'
import '@/index.css'

// A rebuild replaces every hashed chunk, so a tab still holding the previous shell 404s the
// moment it fetches one and that screen is dead until somebody reloads by hand. Vite reports
// exactly that as `vite:preloadError`; one automatic reload fetches the current shell, whose
// chunk names resolve again. The flag makes it one reload per tab session, so a deployment that
// is genuinely broken degrades to the plain failure instead of a reload loop.
const CHUNK_RELOAD_FLAG = 'dirigent.staleChunkReloaded'
window.addEventListener('vite:preloadError', (event) => {
    try {
        if (sessionStorage.getItem(CHUNK_RELOAD_FLAG) === '1') return
        sessionStorage.setItem(CHUNK_RELOAD_FLAG, '1')
    } catch {
        return
    }
    event.preventDefault()
    window.location.reload()
})

registerDirigentFormats()

// Every library graph lays out with the app's elk: its own chunk, one worker for the tab.
setElkEngine(() => elkEngine())

// The editor reads FHIRPath and CQL, and their media types, through the fhir plugin.
registerPlugins([fhir])

/** Wears the stored look on `<html>`, both theme axes, and follows it as it changes. */
function Appearance() {
    useAppearance(APPEARANCE_DEFAULTS, APPEARANCE_OFFER)
    return null
}

/** How the library draws an internal link: through the router, so a press moves without a reload. */
function routedLink({ href, ...props }: RoutedLinkProps) {
    return <RouterLink to={href} {...props} />
}

/** Which links the router follows: the library's internal ones, less the pages the server draws. */
function routedHere(props: RoutedLinkProps) {
    return isInternalLink(props) && !servedByInstance(props.href)
}

createRoot(document.getElementById('root')!).render(
    <StrictMode>
        <Appearance />
        {/* Slow enough that a tooltip is an answer somebody waited for rather than noise
            chasing the pointer. */}
        <TooltipProvider delay={600}>
            <BrowserRouter>
                <LinkProvider render={routedLink} internal={routedHere}>
                    <StatusProvider statuses={STATUSES} dot fallback={FALLBACK}>
                        <App />
                    </StatusProvider>
                </LinkProvider>
            </BrowserRouter>
            <Toaster richColors />
        </TooltipProvider>
    </StrictMode>,
)
