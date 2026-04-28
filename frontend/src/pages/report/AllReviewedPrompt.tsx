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

  // Detect transition from not-all-reviewed → all-reviewed
  useEffect(() => {
    // Don't track transitions until result data has loaded
    if (!result) return

    // First render with data — just record current state, don't trigger.
    // This prevents a false positive when all failures are already reviewed
    // on load, even if result and reviews arrive in separate render batches.
    if (!hasSettledRef.current) {
      hasSettledRef.current = true
      prevAllReviewedRef.current = allReviewed
      return
    }

    if (allReviewed && !prevAllReviewedRef.current && reportportalAvailable) {
      setDialogOpen(true)
    }
    prevAllReviewedRef.current = allReviewed
  }, [allReviewed, reportportalAvailable, result])

  // Reset state when navigating to a different report
  useEffect(() => {
    prevAllReviewedRef.current = false
    hasSettledRef.current = false
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
