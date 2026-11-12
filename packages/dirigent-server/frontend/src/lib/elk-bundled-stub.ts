/**
 * Stands in for `elkjs/lib/elk.bundled.js`, which sokkel-ui-graph constructs only when no engine
 * was set. The app sets elk in a worker at startup, so calling this means that was skipped.
 */
export default function ElkBundledStub(): never {
    throw new Error(
        'elkjs/lib/elk.bundled.js is not bundled: set an engine with setElkEngine from @winterop-com/sokkel-ui-graph/layout before a graph is laid out',
    )
}
