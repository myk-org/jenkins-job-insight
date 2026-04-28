import { useState, useCallback } from 'react'
import { api } from '@/lib/api'
import { getUsername } from '@/lib/cookies'
import { useReportState, useReportDispatch, reviewKey } from './ReportContext'

/* ------------------------------------------------------------------ */
/*  Detection helper                                                   */
/* ------------------------------------------------------------------ */

const URL_RE = /https?:\/\//
const KEYWORD_RE = /\b(known issue|fixed|root cause|workaround|resolved|bug filed|jira|tracked|duplicate)\b/i

/** Returns true if the comment text implies the failure has been reviewed. */
export function suggestsReviewed(commentText: string): boolean {
  if (URL_RE.test(commentText)) return true
  return KEYWORD_RE.test(commentText)
}

/* ------------------------------------------------------------------ */
/*  Hook                                                               */
/* ------------------------------------------------------------------ */

interface UseReviewSuggestionOptions {
  jobId: string
  testName: string
  childJobName?: string
  childBuildNumber?: number
}

export function useReviewSuggestion({ jobId, testName, childJobName, childBuildNumber }: UseReviewSuggestionOptions) {
  const { reviews } = useReportState()
  const dispatch = useReportDispatch()
  const [showSuggestion, setShowSuggestion] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const key = reviewKey(testName, childJobName, childBuildNumber)
  const isAlreadyReviewed = reviews[key]?.reviewed ?? false

  /** Call after a comment is added. If it implies review and not already reviewed, show the prompt. */
  const maybeSuggest = useCallback(
    (commentText: string) => {
      if (isAlreadyReviewed) return
      if (suggestsReviewed(commentText)) {
        setShowSuggestion(true)
      }
    },
    [isAlreadyReviewed],
  )

  const dismissSuggestion = useCallback(() => {
    setShowSuggestion(false)
  }, [])

  const confirmSuggestion = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.put<{ status: string; reviewed_by: string }>(`/results/${jobId}/reviewed`, {
        test_name: testName,
        reviewed: true,
        child_job_name: childJobName ?? '',
        child_build_number: childBuildNumber ?? 0,
      })
      const username = res.reviewed_by ?? getUsername()
      dispatch({
        type: 'SET_REVIEW',
        payload: { key, state: { reviewed: true, username, updated_at: new Date().toISOString() } },
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to mark as reviewed')
    } finally {
      setLoading(false)
      setShowSuggestion(false)
    }
  }, [jobId, testName, childJobName, childBuildNumber, key, dispatch])

  return { showSuggestion, loading, error, maybeSuggest, dismissSuggestion, confirmSuggestion }
}
