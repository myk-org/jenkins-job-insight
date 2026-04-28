import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FeedbackDialog } from '../FeedbackDialog'

// Mock the api module
vi.mock('@/lib/api', () => ({
  api: {
    post: vi.fn(),
    get: vi.fn(),
  },
  getRecentFailedCalls: vi.fn(() => []),
  ApiError: class extends Error {
    status: number
    statusText: string
    body: unknown
    constructor(status: number, statusText: string, body: unknown) {
      super(`API error ${status}: ${statusText}`)
      this.status = status
      this.statusText = statusText
      this.body = body
    }
  },
}))

// Mock errorCapture
vi.mock('@/lib/errorCapture', () => ({
  getRecentErrors: vi.fn(() => ['error1', 'error2']),
}))

import { api, getRecentFailedCalls } from '@/lib/api'

const mockPost = api.post as ReturnType<typeof vi.fn>
const mockGetFailedCalls = getRecentFailedCalls as ReturnType<typeof vi.fn>

describe('FeedbackDialog', () => {
  const onOpenChange = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders form with type selector and textarea when open', () => {
    render(<FeedbackDialog open={true} onOpenChange={onOpenChange} />)
    expect(screen.getByText('Send Feedback')).toBeInTheDocument()
    expect(screen.getByText('Bug Report')).toBeInTheDocument()
    expect(screen.getByText('Feature Request')).toBeInTheDocument()
    expect(screen.getByLabelText('Description')).toBeInTheDocument()
  })

  it('disables submit when description is empty', () => {
    render(<FeedbackDialog open={true} onOpenChange={onOpenChange} />)
    expect(screen.getByRole('button', { name: /submit/i })).toBeDisabled()
  })

  it('enables submit when description is provided', async () => {
    const user = userEvent.setup()
    render(<FeedbackDialog open={true} onOpenChange={onOpenChange} />)
    await user.type(screen.getByLabelText('Description'), 'Something broke')
    expect(screen.getByRole('button', { name: /submit/i })).toBeEnabled()
  })

  it('switches feedback type when toggled', async () => {
    const user = userEvent.setup()
    render(<FeedbackDialog open={true} onOpenChange={onOpenChange} />)
    const featureBtn = screen.getByText('Feature Request')
    await user.click(featureBtn)
    // The placeholder should change
    expect(screen.getByPlaceholderText(/feature you'd like to see/i)).toBeInTheDocument()
  })

  it('submits feedback and shows success', async () => {
    mockPost.mockResolvedValue({ issue_url: 'https://github.com/org/repo/issues/42', issue_key: '#42' })
    mockGetFailedCalls.mockReturnValue([])
    const user = userEvent.setup()
    render(<FeedbackDialog open={true} onOpenChange={onOpenChange} />)
    await user.type(screen.getByLabelText('Description'), 'Page crashes on load')
    await user.click(screen.getByRole('button', { name: /submit/i }))
    await waitFor(() => expect(screen.getByText('Thank you for your feedback!')).toBeInTheDocument())
    expect(screen.getByText('View issue')).toHaveAttribute('href', 'https://github.com/org/repo/issues/42')
    expect(mockPost).toHaveBeenCalledWith('/api/feedback', expect.objectContaining({
      feedback_type: 'bug',
      description: 'Page crashes on load',
      user_agent: expect.any(String),
      console_errors: ['error1', 'error2'],
    }))
  })

  it('shows error message on submit failure', async () => {
    mockPost.mockRejectedValue(new Error('API error 500: Internal Server Error'))
    const user = userEvent.setup()
    render(<FeedbackDialog open={true} onOpenChange={onOpenChange} />)
    await user.type(screen.getByLabelText('Description'), 'Some feedback')
    await user.click(screen.getByRole('button', { name: /submit/i }))
    await waitFor(() => expect(screen.getByText(/API error 500/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('Try Again returns to form state', async () => {
    mockPost.mockRejectedValue(new Error('Network error'))
    const user = userEvent.setup()
    render(<FeedbackDialog open={true} onOpenChange={onOpenChange} />)
    await user.type(screen.getByLabelText('Description'), 'Some feedback')
    await user.click(screen.getByRole('button', { name: /submit/i }))
    await waitFor(() => expect(screen.getByText(/Network error/)).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(screen.getByText('Send Feedback')).toBeInTheDocument()
    expect(screen.getByLabelText('Description')).toBeInTheDocument()
  })

  it('includes failed API calls in the payload', async () => {
    mockPost.mockResolvedValue({ issue_url: '', issue_key: '' })
    mockGetFailedCalls.mockReturnValue([
      { status: 500, endpoint: '/api/test', error: 'server error', timestamp: 123 },
    ])
    const user = userEvent.setup()
    render(<FeedbackDialog open={true} onOpenChange={onOpenChange} />)
    await user.type(screen.getByLabelText('Description'), 'Bug report')
    await user.click(screen.getByRole('button', { name: /submit/i }))
    await waitFor(() => expect(mockPost).toHaveBeenCalled())
    const payload = mockPost.mock.calls[0][1]
    expect(payload.failed_api_calls).toEqual([
      { status: 500, endpoint: '/api/test', error: 'server error' },
    ])
  })
})
