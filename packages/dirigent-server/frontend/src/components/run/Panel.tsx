import { CopyButton } from '@winterop-com/sokkel-ui/CopyButton'

import { copyWords } from '@/lib/library-words'

/** A machine's string beside the button that copies it. */
export function Copyable({ value, label }: { value: string; label: string }) {
    return (
        <span className="flex items-start gap-1">
            <span className="identifier">{value}</span>
            <CopyButton value={value} size="icon-xs" words={copyWords(label)} />
        </span>
    )
}
