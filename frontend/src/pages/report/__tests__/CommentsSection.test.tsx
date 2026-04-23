import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { CommentsSection } from '../CommentsSection'
import { ReportProvider, useReportDispatch } from '../ReportContext'
import type { Comment } from '@/types'

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

const mockUsername = 'testuser'

vi.mock('@/lib/cookies', () => ({
  getUsername: () => mockUsername,
}))

const mockDelete = vi.fn()
const mockPost = vi.fn()

vi.mock('@/lib/api', () => ({
  api: {
    delete: (...args: unknown[]) => mockDelete(...args),
    post: (...args: unknown[]) => mockPost(...args),
  },
}))

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function makeComment(overrides: Partial<Comment> = {}): Comment {
  return {
    id: 1,
    job_id: 'job-1',
    test_name: 'test-a',
    child_job_name: '',
    child_build_number: 0,
    comment: 'A test comment',
    username: mockUsername,
    created_at: '2025-01-01T00:00:00Z',
    ...overrides,
  }
}

/**
 * Helper child that injects comments into ReportContext, then renders CommentsSection.
 */
function Injector({ comments }: { comments: Comment[] }) {
  const dispatch = useReportDispatch()
  useEffect(() => {
    dispatch({
      type: 'SET_COMMENTS_AND_REVIEWS',
      payload: { comments, reviews: {} },
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <CommentsSection
      jobId="job-1"
      testNames={['test-a']}
    />
  )
}

function renderWithComments(comments: Comment[]) {
  return render(
    <ReportProvider>
      <Injector comments={comments} />
    </ReportProvider>,
  )
}

/* ------------------------------------------------------------------ */
/*  Tests                                                              */
/* ------------------------------------------------------------------ */

beforeEach(() => {
  vi.clearAllMocks()
  mockDelete.mockResolvedValue({})
  mockPost.mockResolvedValue({ enrichments: {} })
})

describe('CommentsSection – delete confirmation', () => {
  it('shows a confirmation dialog when the delete button is clicked', async () => {
    renderWithComments([makeComment()])

    const deleteBtn = screen.getByRole('button', { name: 'Delete comment' })
    fireEvent.click(deleteBtn)

    expect(screen.getByText('Are you sure you want to delete this comment? This action cannot be undone.')).toBeDefined()
    expect(screen.getByRole('button', { name: 'Delete' })).toBeDefined()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDefined()
  })

  it('does not call the API when cancel is clicked', async () => {
    renderWithComments([makeComment()])

    fireEvent.click(screen.getByRole('button', { name: 'Delete comment' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(mockDelete).not.toHaveBeenCalled()
  })

  it('calls the delete API when confirm is clicked', async () => {
    renderWithComments([makeComment({ id: 42 })])

    fireEvent.click(screen.getByRole('button', { name: 'Delete comment' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => {
      expect(mockDelete).toHaveBeenCalledWith('/results/job-1/comments/42')
    })
  })

  it('closes the dialog after successful deletion', async () => {
    renderWithComments([makeComment()])

    fireEvent.click(screen.getByRole('button', { name: 'Delete comment' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => {
      expect(screen.queryByText('Are you sure you want to delete this comment? This action cannot be undone.')).toBeNull()
    })
  })

  it('does not show delete button for comments by other users', () => {
    renderWithComments([makeComment({ username: 'other-user' })])

    expect(screen.queryByRole('button', { name: 'Delete comment' })).toBeNull()
  })

  it('shows an error when deletion fails', async () => {
    mockDelete.mockRejectedValueOnce(new Error('Network error'))
    renderWithComments([makeComment()])

    fireEvent.click(screen.getByRole('button', { name: 'Delete comment' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeDefined()
      expect(screen.getByText('Network error')).toBeDefined()
    })
  })
})
