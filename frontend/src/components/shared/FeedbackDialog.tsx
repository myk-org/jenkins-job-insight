import { useState, useRef, useEffect } from 'react'
import { api } from '@/lib/api'
import { getRecentFailedCalls } from '@/lib/api'
import { getRecentErrors } from '@/lib/errorCapture'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { LoadingSpinner } from '@/components/shared/LoadingSpinner'
import { CheckCircle2, ExternalLink, Bug, Lightbulb } from 'lucide-react'
import type { FeedbackRequest, FeedbackResponse } from '@/types'

type FeedbackType = 'bug' | 'feature'
type Phase = 'form' | 'submitting' | 'success' | 'error'

interface FeedbackDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function FeedbackDialog({ open, onOpenChange }: FeedbackDialogProps) {
  const [feedbackType, setFeedbackType] = useState<FeedbackType>('bug')
  const [description, setDescription] = useState('')
  const [phase, setPhase] = useState<Phase>('form')
  const [issueUrl, setIssueUrl] = useState('')
  const [errorMsg, setErrorMsg] = useState('')
  const cancelledRef = useRef(false)

  // Track dialog open/close to guard async setState
  useEffect(() => {
    if (open) {
      cancelledRef.current = false
    } else {
      cancelledRef.current = true
    }
  }, [open])

  function collectPageState(): FeedbackRequest['page_state'] {
    const state: FeedbackRequest['page_state'] = {
      url: window.location.href,
    }
    // Extract report_id from URL if on a report page
    const reportMatch = window.location.pathname.match(/\/results\/([^/]+)/)
    if (reportMatch) {
      state.report_id = reportMatch[1]
    }
    // Capture active filters from URL search params
    const params = new URLSearchParams(window.location.search)
    const filters = params.toString()
    if (filters) {
      state.active_filters = filters
    }
    return state
  }

  async function handleSubmit() {
    if (!description.trim()) return

    setPhase('submitting')
    try {
      const failedCalls = getRecentFailedCalls()
      const payload: FeedbackRequest = {
        feedback_type: feedbackType,
        description: description.trim(),
        console_errors: getRecentErrors(),
        failed_api_calls: failedCalls.map(({ status, endpoint, error }) => ({
          status,
          endpoint,
          error,
        })),
        page_state: collectPageState(),
        user_agent: navigator.userAgent,
      }

      const res = await api.post<FeedbackResponse>('/api/feedback', payload)
      if (!cancelledRef.current) {
        setIssueUrl(res.issue_url)
        setPhase('success')
      }
    } catch (err) {
      if (!cancelledRef.current) {
        setErrorMsg(err instanceof Error ? err.message : 'Failed to submit feedback')
        setPhase('error')
      }
    }
  }

  function handleClose(nextOpen: boolean) {
    if (nextOpen) return
    onOpenChange(false)
    setTimeout(() => {
      setPhase('form')
      setFeedbackType('bug')
      setDescription('')
      setIssueUrl('')
      setErrorMsg('')
    }, 200)
  }

  const typeOptions: { value: FeedbackType; label: string; icon: typeof Bug }[] = [
    { value: 'bug', label: 'Bug Report', icon: Bug },
    { value: 'feature', label: 'Feature Request', icon: Lightbulb },
  ]

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{phase === 'success' ? 'Feedback Submitted' : 'Send Feedback'}</DialogTitle>
          {phase === 'form' && (
            <DialogDescription>
              Report a bug or suggest a feature. Browser context is attached automatically.
            </DialogDescription>
          )}
        </DialogHeader>

        {/* Form */}
        {phase === 'form' && (
          <div className="space-y-4">
            {/* Type selector */}
            <div className="flex gap-2">
              {typeOptions.map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setFeedbackType(value)}
                  className={`flex flex-1 items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                    feedbackType === value
                      ? 'border-border-accent bg-surface-elevated text-text-primary'
                      : 'border-border-default text-text-tertiary hover:bg-surface-hover hover:text-text-secondary'
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {label}
                </button>
              ))}
            </div>

            {/* Description */}
            <div className="space-y-2">
              <label htmlFor="feedback-description" className="text-xs font-display uppercase tracking-widest text-text-tertiary">
                Description
              </label>
              <Textarea
                id="feedback-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder={
                  feedbackType === 'bug'
                    ? 'Describe the bug: what happened vs. what you expected...'
                    : 'Describe the feature you\'d like to see...'
                }
                rows={6}
              />
            </div>

            <p className="text-xs text-text-tertiary">
              Console errors, recent failed API calls, and page context will be included automatically.
            </p>
          </div>
        )}

        {/* Submitting */}
        {phase === 'submitting' && (
          <div className="flex flex-col items-center gap-4 py-8">
            <LoadingSpinner size="lg" />
            <p className="text-sm text-text-secondary">Submitting feedback...</p>
          </div>
        )}

        {/* Success */}
        {phase === 'success' && (
          <div className="flex flex-col items-center gap-4 py-8 animate-scale-in">
            <div className="flex h-16 w-16 items-center justify-center rounded-full bg-signal-green/15">
              <CheckCircle2 className="h-8 w-8 text-signal-green" />
            </div>
            <p className="text-sm text-text-secondary">Thank you for your feedback!</p>
            {issueUrl && (
              <a
                href={issueUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-1 text-sm text-text-link hover:underline"
              >
                View issue <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
          </div>
        )}

        {/* Error */}
        {phase === 'error' && (
          <div className="flex flex-col items-center gap-4 py-8">
            <p className="text-sm text-signal-red">{errorMsg}</p>
          </div>
        )}

        <DialogFooter className="flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-end">
          {phase === 'form' && (
            <div className="flex gap-2 sm:ml-auto">
              <Button variant="ghost" onClick={() => handleClose(false)}>Cancel</Button>
              <Button onClick={handleSubmit} disabled={!description.trim()}>Submit</Button>
            </div>
          )}
          {phase === 'error' && (
            <div className="flex gap-2 sm:ml-auto">
              <Button variant="ghost" onClick={() => handleClose(false)}>Close</Button>
              <Button onClick={() => setPhase('form')}>Try Again</Button>
            </div>
          )}
          {phase === 'success' && (
            <Button variant="ghost" onClick={() => handleClose(false)} className="sm:ml-auto">Close</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
