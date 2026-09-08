import { useState } from 'react'

import { Refusal } from '@/components/Refusal'
import { CodePane } from '@/components/pipeline/CodePane'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { type JsonMap, type Problem } from '@/lib/api'
import { local, refusalOf } from '@/lib/refusal'
import { createSchema } from '@/lib/schemas'

const PLACEHOLDER = `{
  "$id": "org-unit",
  "title": "Organisation unit",
  "type": "object",
  "required": ["id", "displayName"],
  "properties": {
    "id": { "type": "string" },
    "displayName": { "type": "string" }
  }
}`

/**
 * Write a JSON Schema and store it.
 *
 * A SCHEMA IS AUTHORED HERE, not fetched: the box is the schema itself, written to say what a
 * payload should look like. Its code, name and description come from the schema's own `$id`,
 * `title` and `description` -- so a well-formed schema needs nothing else, and the code box is
 * only for a schema that names no `$id`.
 *
 * THE REFUSAL IS THE SERVER'S. A body that is not itself valid JSON Schema, or one that names
 * no code any way, arrives as a problem document and is shown as one, because the server's
 * sentence names the fault and this dialog could only paraphrase it.
 */
export function NewSchema({
    open,
    onOpenChange,
    onCreated,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    onCreated: () => void
}) {
    const [text, setText] = useState('')
    const [code, setCode] = useState('')
    const [problem, setProblem] = useState<Problem | null>(null)
    const [saving, setSaving] = useState(false)

    const store = () => {
        setProblem(null)
        let body: JsonMap
        try {
            body = JSON.parse(text || '{}') as JsonMap
        } catch (error) {
            setProblem(local(`The schema is not readable JSON: ${String(error)}`))
            return
        }
        setSaving(true)
        void createSchema(body, code.trim() || null)
            .then(() => {
                setText('')
                setCode('')
                onOpenChange(false)
                onCreated()
            })
            .catch((error: unknown) => {
                setProblem(refusalOf(error))
            })
            .finally(() => {
                setSaving(false)
            })
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="flex h-[80vh] w-[min(56rem,90vw)] max-w-[min(56rem,90vw)] flex-col gap-3 sm:max-w-[min(56rem,90vw)]">
                <DialogHeader>
                    <DialogTitle>New schema</DialogTitle>
                    <DialogDescription>
                        Its code, title and description come from the schema's own <code>$id</code>,{' '}
                        <code>title</code> and <code>description</code>.
                    </DialogDescription>
                </DialogHeader>
                <div className="border-border min-h-0 flex-1 overflow-hidden rounded-md border">
                    <CodePane
                        value={text}
                        mediaType="application/json"
                        path="new-schema"
                        label="the schema"
                        placeholder={PLACEHOLDER}
                        className="h-full min-h-0"
                        onChange={setText}
                    />
                </div>
                <div className="grid gap-1.5">
                    <Label htmlFor="schema-code">Code</Label>
                    <Input
                        id="schema-code"
                        className="font-mono"
                        placeholder="taken from $id when left blank"
                        value={code}
                        onChange={(event) => {
                            setCode(event.target.value)
                        }}
                    />
                </div>
                {problem !== null && <Refusal problem={problem} />}
                <DialogFooter>
                    <DialogClose
                        render={
                            <Button variant="ghost" size="sm">
                                Cancel
                            </Button>
                        }
                    />
                    <Button size="sm" disabled={saving} onClick={store}>
                        {saving ? 'Storing' : 'Store'}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
