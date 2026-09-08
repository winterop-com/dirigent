import { ThemeProvider } from 'next-themes'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'

import App from '@/App'
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

createRoot(document.getElementById('root')!).render(
    <StrictMode>
        {/* The mode axis. `class` matches the `.dark` variant index.css defines, and the palette
            axis is `data-theme`, written before first paint by the script in index.html. */}
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
            {/* Slow enough that a tooltip is an answer somebody waited for rather than noise
                chasing the pointer. */}
            <TooltipProvider delay={600}>
                <BrowserRouter>
                    <App />
                </BrowserRouter>
                <Toaster richColors />
            </TooltipProvider>
        </ThemeProvider>
    </StrictMode>,
)
