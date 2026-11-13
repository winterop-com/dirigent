import { describe, expect, it } from 'vitest'

import { referenceFor } from '@/components/pipeline/ProgramReference'

describe('the program reference', () => {
    it('has a reference for a FHIRPath expression and a CQL library', () => {
        expect(referenceFor('application/fhirpath')?.title).toBe('FHIRPath')
        expect(referenceFor('text/cql')?.title).toBe('CQL')
    })

    it('has none for a media type it does not know', () => {
        expect(referenceFor('text/plain')).toBeNull()
    })
})
