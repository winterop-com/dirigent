import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiJson, apiSend } from '@/lib/api'
import { authStore, refreshIdentity, signIn } from '@/lib/auth'

vi.mock('@/lib/api', async (original) => ({
    ...(await original<typeof import('@/lib/api')>()),
    apiJson: vi.fn(),
    apiSend: vi.fn(),
}))

const unauthorized = () =>
    new ApiError({
        status: 401,
        title: 'Unauthorized',
        detail: 'not signed in',
        code: 'server.not_signed_in',
        params: {},
        problems: [],
        instance: null,
    })

afterEach(() => {
    vi.resetAllMocks()
    authStore.set({ status: 'unknown', identity: null, problem: null, working: false })
})

describe('refreshIdentity', () => {
    it('answers a 401 with signed out', async () => {
        vi.mocked(apiJson).mockRejectedValue(unauthorized())
        await refreshIdentity()
        expect(authStore.get()).toEqual({
            status: 'signed-out',
            identity: null,
            problem: null,
            working: false,
        })
    })

    it('leaves a sign-in in flight working when its 401 lands first', async () => {
        let refuse: (error: unknown) => void = () => undefined
        vi.mocked(apiSend).mockReturnValue(
            new Promise((_, reject) => {
                refuse = reject
            }),
        )
        vi.mocked(apiJson).mockRejectedValue(unauthorized())

        const trying = signIn('admin', 'wrong')
        await refreshIdentity()
        expect(authStore.get()).toMatchObject({ status: 'signed-out', working: true, problem: null })

        refuse(unauthorized())
        expect(await trying).toBe(false)
        expect(authStore.get()).toMatchObject({
            status: 'signed-out',
            working: false,
            problem: { status: 401 },
        })
    })
})
