/**
 * A module-level store, which is how a fact several screens share is held.
 *
 * There is no react-query, swr or zustand in this app. What crosses a page boundary here is
 * small and long-lived -- who is signed in, whether the rail is collapsed, which theme is
 * painted -- and a store per fact, read through `useSyncExternalStore`, is the whole of what
 * that needs. A page's own reads stay in the page's own `useState`.
 *
 * NOTHING HERE IMPORTS REACT, so a store is exercised in plain Node. `hooks/use-store` is the
 * one line that binds one to a component.
 *
 * THE SNAPSHOT MUST BE REFERENTIALLY STABLE. `useSyncExternalStore` re-renders whenever the
 * snapshot differs by `Object.is`, and calls it on every render, so a store that built a new
 * object each read would loop forever. `set` therefore holds the value it was given and
 * publishes only when it actually changed.
 */

/** One fact, and the ways to read, change, and watch it. */
export interface Store<T> {
    /** The value as of this instant. Stable between changes. */
    get: () => T
    /** Replace the value. A value equal by `Object.is` to the current one notifies nobody. */
    set: (next: T) => void
    /** Replace the value by deriving it from the current one. */
    update: (change: (current: T) => T) => void
    /** Watch for changes; the returned function stops watching. */
    subscribe: (listener: () => void) => () => void
}

/** Build a store around one initial value. */
export function createStore<T>(initial: T): Store<T> {
    let current = initial
    const listeners = new Set<() => void>()

    const get = (): T => current

    const set = (next: T): void => {
        if (Object.is(next, current)) return
        current = next
        // A copy, because a listener may unsubscribe itself while it is being called and
        // deleting from the set mid-iteration would skip whichever listener followed it.
        const watching = Array.from(listeners)
        for (const listener of watching) listener()
    }

    return {
        get,
        set,
        update: (change) => {
            set(change(current))
        },
        subscribe: (listener) => {
            listeners.add(listener)
            return () => {
                listeners.delete(listener)
            }
        },
    }
}
