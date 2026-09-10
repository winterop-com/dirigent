/**
 * Where the versioned API is mounted, for the one thing that is not a fetch: an href.
 *
 * `apiFetch` composes the prefix onto every request, so nothing that reads has to know it. A
 * link a reader can save a file from is an anchor rather than a request, so the screen that
 * draws one has to write the whole path itself -- and this bundle cannot know at build time
 * what the prefix is, because `Settings.api_prefix` is configurable and the instance answers
 * with it. It is cached for the life of the tab, so this is one read however many rows ask.
 *
 * It answers null until the read lands, and null again if it fails, which is a screen drawing
 * the row without a link rather than a link that would go nowhere.
 */

import { useEffect, useState } from 'react'

import { appConfig } from '@/lib/api'

export function useApiPrefix(): string | null {
    const [prefix, setPrefix] = useState<string | null>(null)

    useEffect(() => {
        let cancelled = false
        void appConfig().then(
            (config) => {
                if (!cancelled) setPrefix(config.api_prefix)
            },
            () => {
                // The instance did not answer what it is. Every row is still drawn; it is the
                // link to the content that is missing.
            },
        )
        return () => {
            cancelled = true
        }
    }, [])

    return prefix
}
