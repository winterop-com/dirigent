import { useSyncExternalStore } from 'react'

import type { Store } from '@/lib/store'

/** Read a module store in a component, re-rendering when it changes. */
export function useStore<T>(store: Store<T>): T {
    return useSyncExternalStore(store.subscribe, store.get, store.get)
}
