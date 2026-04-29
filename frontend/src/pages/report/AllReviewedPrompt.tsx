import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { collectAllTestKeys } from '@/lib/failureKeys'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { useReportState } from './ReportContext'

interface AllReviewedPromptProps {
  jobId: string
}

export function AllReviewedPrompt({ jobId }: AllReviewedPromptProps) {
  const { result, reviews, reportportalAvailable } = useReportState()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [pushing, setPushing] = useState(false)
  const prevAllReviewedRef = useRef(false)
  const hasSettledRef = useRef(false)
  const justSettledRef = useRef(false)

  const allKeys = useMemo(
    () =>
      result
        ? collectAllTestKeys(
            result.failures ?? [],
            result.child_job_analyses ?? [],
          )
        : [],
    [result],
  )

  const allReviewed = useMemo(() => {
    if (allKeys.length === 0) return false
    return allKeys.every((k) => reviews[k]?.reviewed)
  }, [allKeys, reviews])

  // Keep a ref to the latest allReviewed value for the microtask
  const allReviewedRef = useRef(allReviewed)
  allReviewedRef.current = allReviewed

  // Effect 1: Wait for result to load, then capture initial allReviewed state.
  // Only watches `result` — immune to comment-poll re-renders.
  useEffect(() => {
    if (!result || hasSettledRef.current) return
    hasSettledRef.current = true
    justSettledRef.current = true
    // Use a microtask to ensure reviews have also been applied
    // before we capture the initial allReviewed state
    queueMicrotask(() => {
      prevAllReviewedRef.current = allReviewedRef.current
      justSettledRef.current = false
    })
  }, [result])

  // Effect 2: Detect transitions from not-all-reviewed → all-reviewed (only after settled)
  useEffect(() => {
    if (!hasSettledRef.current || justSettledRef.current) return
    if (allReviewed && !prevAllReviewedRef.current && reportportalAvailable) {
      setDialogOpen(true)
    }
    prevAllReviewedRef.current = allReviewed
  }, [allReviewed, reportportalAvailable])

  // Reset state when navigating to a different report
  useEffect(() => {
    prevAllReviewedRef.current = false
    hasSettledRef.current = false
    justSettledRef.current = false
    setDialogOpen(false)
    setPushing(false)
  }, [jobId])

  const handleConfirm = async () => {
    setPushing(true)
    try {
      await api.post(`/results/${jobId}/push-reportportal`)
    } catch {
      // Best-effort — errors are not surfaced here
    } finally {
      setPushing(false)
      setDialogOpen(false)
    }
  }

  if (!reportportalAvailable) return null

  return (
    <ConfirmDialog
      open={dialogOpen}
      onOpenChange={setDialogOpen}
      title="All failures reviewed"
      description="All failures reviewed. Update Report Portal?"
      confirmLabel="Yes"
      cancelLabel="No"
      onConfirm={handleConfirm}
      loading={pushing}
    />
  )
}
