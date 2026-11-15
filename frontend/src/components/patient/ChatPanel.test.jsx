// @vitest-environment jsdom
import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { chatService } from '../../services/auth'
import ChatPanel from './ChatPanel'

vi.mock('../../services/auth', () => ({
  chatService: {
    sessions: vi.fn(),
    createSession: vi.fn(),
    session: vi.fn(),
    send: vi.fn(),
    deleteSession: vi.fn(),
  },
}))

vi.mock('../../api/client', () => ({
  apiError: (error) => ({ code: 'CHAT_ERROR', message: error.message }),
}))

const session = { id: 12, patient: 7, title: 'New conversation' }

beforeEach(() => {
  vi.clearAllMocks()
  Element.prototype.scrollIntoView = vi.fn()
  chatService.sessions.mockResolvedValue({ sessions: [] })
  chatService.createSession.mockResolvedValue({ session })
  chatService.session.mockResolvedValue({ messages: [] })
  chatService.send.mockResolvedValue({
    reply: { role: 'ASSISTANT', content: 'Assistant response' },
  })
})

afterEach(cleanup)

describe('ChatPanel message sending', () => {
  it('creates a private session on the first valid send and shows the reply', async () => {
    render(<ChatPanel patientId={7} />)

    const input = screen.getByPlaceholderText(/type your question/i)
    const send = screen.getByRole('button', { name: 'Send' })
    await waitFor(() => expect(chatService.sessions).toHaveBeenCalled())
    await waitFor(() => expect(input.disabled).toBe(false))
    expect(send.disabled).toBe(true)

    fireEvent.change(input, { target: { value: '  What is antenatal care?  ' } })
    expect(send.disabled).toBe(false)
    fireEvent.click(send)

    await screen.findByText('Assistant response')
    expect(chatService.createSession).toHaveBeenCalledWith(7, '')
    expect(chatService.send).toHaveBeenCalledWith(session.id, 'What is antenatal care?')
  })

  it('submits Enter and preserves Shift+Enter for a newline', async () => {
    render(<ChatPanel patientId={7} />)
    const input = screen.getByPlaceholderText(/type your question/i)
    await waitFor(() => expect(chatService.sessions).toHaveBeenCalled())
    await waitFor(() => expect(input.disabled).toBe(false))
    fireEvent.change(input, { target: { value: 'A question' } })

    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', shiftKey: true })
    expect(chatService.send).not.toHaveBeenCalled()
    fireEvent.keyDown(input, { key: 'Enter', code: 'Enter' })

    await screen.findByText('Assistant response')
    expect(chatService.send).toHaveBeenCalledTimes(1)
  })

  it('prevents duplicate submissions while the request is pending', async () => {
    let finishSend
    chatService.send.mockReturnValue(new Promise((resolve) => { finishSend = resolve }))
    render(<ChatPanel patientId={7} />)
    const input = screen.getByPlaceholderText(/type your question/i)
    await waitFor(() => expect(chatService.sessions).toHaveBeenCalled())
    await waitFor(() => expect(input.disabled).toBe(false))
    fireEvent.change(input, { target: { value: 'One message' } })
    const form = input.closest('form')

    fireEvent.submit(form)
    fireEvent.submit(form)

    await waitFor(() => expect(chatService.send).toHaveBeenCalledTimes(1))
    expect(document.body.contains(screen.getByRole('status'))).toBe(true)
    finishSend({ reply: { role: 'ASSISTANT', content: 'Done' } })
    await screen.findByText('Done')
  })

  it('shows a meaningful error when the message request fails', async () => {
    chatService.send.mockRejectedValue(new Error('Chat service unavailable'))
    render(<ChatPanel patientId={7} />)
    const input = screen.getByPlaceholderText(/type your question/i)
    await waitFor(() => expect(chatService.sessions).toHaveBeenCalled())
    await waitFor(() => expect(input.disabled).toBe(false))
    fireEvent.change(input, { target: { value: 'A question' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect((await screen.findByRole('alert')).textContent).toContain('Chat service unavailable')
  })
})
