import { SecretField } from '@/components/connections/SecretField'
import { SectionHeading } from '@/components/ds/SectionHeading'
import { FormField } from '@/components/ds/FormField'
import { SchemaForm } from '@/components/pipeline/SchemaForm'
import { Refusal } from '@/components/Refusal'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { type ConnectionEdit } from '@/hooks/use-connection-edit'
import { type ConnectionOut } from '@/lib/connections'
import { LABELS } from '@/lib/labels'

/**
 * The boxes a connection's dialog holds in its edit state.
 *
 * THE KIND AND THE CODE ARE FIXED. `PATCH /connections/{code}` changes the name, the description
 * and the config, and nothing else: a connection of a different kind is a different connection,
 * and one addressed by a different code is a different connection too.
 */
export function ConnectionForm({ connection, form }: { connection: ConnectionOut; form: ConnectionEdit }) {
    return (
        <>
            <FormField id="connection-name" label={LABELS.word.name.label}>
                <Input
                    id="connection-name"
                    value={form.named}
                    onChange={(event) => {
                        form.setNamed(event.target.value)
                    }}
                />
            </FormField>

            <FormField id="connection-description" label={LABELS.word.description}>
                <Textarea
                    id="connection-description"
                    className="h-20"
                    value={form.description}
                    onChange={(event) => {
                        form.setDescription(event.target.value)
                    }}
                    placeholder={LABELS.connections.description_placeholder}
                />
            </FormField>

            <div className="space-y-3">
                <SectionHeading tier="group">{LABELS.connections.settings_heading}</SectionHeading>
                <SchemaForm
                    fields={form.fields}
                    values={form.values}
                    problems={form.problems}
                    columns
                    onChange={form.setting}
                    onUnreadable={form.unreadable}
                />
            </div>

            {connection.secret_fields.length > 0 && (
                <div className="space-y-3">
                    <SectionHeading tier="group">{LABELS.connections.secrets_heading}</SectionHeading>
                    <div className="grid gap-4 sm:grid-cols-2">
                        {connection.secret_fields.map((name) => (
                            <SecretField
                                key={name}
                                id={`secret-${name}`}
                                name={name}
                                stored={isSet(connection.config[name])}
                                value={form.secrets[name] ?? ''}
                                onChange={(typed) => {
                                    form.secret(name, typed)
                                }}
                            />
                        ))}
                    </div>
                </div>
            )}

            {form.problem !== null && <Refusal problem={form.problem} />}
        </>
    )
}

/** Whether the instance holds a credential for this field, which is all a read can say. */
function isSet(value: unknown): boolean {
    return value !== null && value !== undefined
}
