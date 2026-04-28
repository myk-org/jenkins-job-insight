import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { useEffect } from 'react'
import { ReportProvider, useReportDispatch } from '../ReportContext'
import { suggestsReviewed, useReviewSuggestion } from '../useReviewSuggestion'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'

/* ------------------------------------------------------------------ */
/*  Mocks                                                              */
/* ------------------------------------------------------------------ */

vi.mock('@/lib/cookies', () => ({
  getUsername: () => 'testuser',
}))

const mockPut = vi.fn()

vi.mock('@/lib/api', () => ({
  api: {
    put: (...args: unknown[]) => mockPut(...args),
    get: vi.fn().mockResolvedValue({ users: [] }),
    post: vi.fn().mockResolvedValue({}),
  },
}))

/* ------------------------------------------------------------------ */
/*  suggestsReviewed unit tests                                        */
/* ------------------------------------------------------------------ */

describe('suggestsReviewed', () => {
  it('returns true for text containing a URL', () => {
    expect(suggestsReviewed('See https://jira.example.com/browse/BUG-123')).toBe(true)
    expect(suggestsReviewed('Fixed in http://github.com/org/repo/pull/42')).toBe(true)
  })

  it('returns true for text containing review-suggesting keywords', () => {
    expect(suggestsReviewed('This is a known issue')).toBe(true)
    expect(suggestsReviewed('Root cause identified')).toBe(true)
    expect(suggestsReviewed('Already fixed in main')).toBe(true)
    expect(suggestsReviewed('Workaround applied')).toBe(true)
    expect(suggestsReviewed('Issue resolved')).toBe(true)
    expect(suggestsReviewed('Bug filed for this')).toBe(true)
    expect(suggestsReviewed('Created JIRA ticket')).toBe(true)
    expect(suggestsReviewed('Tracked in backlog')).toBe(true)
    expect(suggestsReviewed('This is a duplicate of another failure')).toBe(true)
  })

  it('is case-insensitive for keywords', () => {
    expect(suggestsReviewed('KNOWN ISSUE with this test')).toBe(true)
    expect(suggestsReviewed('Root Cause: config mismatch')).toBe(true)
  })

  it('returns false for generic comments', () => {
    expect(suggestsReviewed('Looking into this')).toBe(false)
    expect(suggestsReviewed('Need to investigate')).toBe(false)
    expect(suggestsReviewed('Not sure what happened')).toBe(false)
    expect(suggestsReviewed('')).toBe(false)
  })
})

/* ------------------------------------------------------------------ */
/*  useReviewSuggestion hook integration tests                         */
/* ------------------------------------------------------------------ */

/** Test harness that exposes hook state and actions via rendered UI. */
function HookHarness({ setReviewed }: { setReviewed?: boolean }) {
  const dispatch = useReportDispatch()
  const { showSuggestion, loading, maybeSuggest, dismissSuggestion, confirmSuggestion } = useReviewSuggestion({
    jobId: 'job-1',
    testName: 'test-a',
  })

  // Optionally pre-set the review state
  useEffect(() => {
    if (setReviewed) {
      dispatch({
        type: 'SET_REVIEW',
        payload: { key: 'test-a', state: { reviewed: true, username: 'someone', updated_at: new Date().toISOString() } },
      })
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <span data-testid="show">{String(showSuggestion)}</span>
      <span data-testid="loading">{String(loading)}</span>
      <button data-testid="suggest-url" onClick={() => maybeSuggest('See https://jira.example.com/BUG-1')}>Suggest URL</button>
      <button data-testid="suggest-keyword" onClick={() => maybeSuggest('This is a known issue')}>Suggest Keyword</button>
      <button data-testid="suggest-generic" onClick={() => maybeSuggest('Looking into it')}>Suggest Generic</button>
      <ConfirmDialog
        open={showSuggestion}
        onOpenChange={(open) => { if (!open) dismissSuggestion() }}
        title="Mark as reviewed?"
        description="Would you like to mark it as reviewed?"
        confirmLabel="Yes"
        cancelLabel="No"
        onConfirm={confirmSuggestion}
        loading={loading}
      />
    </>
  )
}

function renderHarness(props: { setReviewed?: boolean } = {}) {
  return render(
    <ReportProvider>
      <HookHarness {...props} />
    </ReportProvider>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockPut.mockResolvedValue({ status: 'ok', reviewed_by: 'testuser' })
})

describe('useReviewSuggestion hook', () => {
  it('does not show suggestion initially', () => {
    renderHarness()
    expect(screen.getByTestId('show').textContent).toBe('false')
  })

  it('shows suggestion when comment contains a URL', () => {
    renderHarness()
    fireEvent.click(screen.getByTestId('suggest-url'))
    expect(screen.getByTestId('show').textContent).toBe('true')
    expect(screen.getByText('Mark as reviewed?')).toBeDefined()
  })

  it('shows suggestion when comment contains a keyword', () => {
    renderHarness()
    fireEvent.click(screen.getByTestId('suggest-keyword'))
    expect(screen.getByTestId('show').textContent).toBe('true')
  })

  it('does not show suggestion for generic comments', () => {
    renderHarness()
    fireEvent.click(screen.getByTestId('suggest-generic'))
    expect(screen.getByTestId('show').textContent).toBe('false')
  })

  it('does not show suggestion when already reviewed', async () => {
    renderHarness({ setReviewed: true })
    // Wait for the SET_REVIEW dispatch to take effect
    await waitFor(() => {})
    fireEvent.click(screen.getByTestId('suggest-url'))
    expect(screen.getByTestId('show').textContent).toBe('false')
  })

  it('dismisses suggestion when No is clicked', () => {
    renderHarness()
    fireEvent.click(screen.getByTestId('suggest-url'))
    expect(screen.getByTestId('show').textContent).toBe('true')

    fireEvent.click(screen.getByRole('button', { name: 'No' }))
    expect(screen.getByTestId('show').textContent).toBe('false')
  })

  it('calls review API and hides dialog when Yes is clicked', async () => {
    renderHarness()
    fireEvent.click(screen.getByTestId('suggest-url'))

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Yes' }))
    })

    await waitFor(() => {
      expect(mockPut).toHaveBeenCalledWith('/results/job-1/reviewed', {
        test_name: 'test-a',
        reviewed: true,
        child_job_name: '',
        child_build_number: 0,
      })
    })

    expect(screen.getByTestId('show').textContent).toBe('false')
  })
})
