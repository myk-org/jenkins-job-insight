import { useState, useRef, useEffect } from 'react'
import { api } from '@/lib/api'
import { formatTimestamp } from '@/lib/utils'
import { isCommentInScope } from '@/lib/grouping'
import { getUsername } from '@/lib/cookies'
import { useReportState, useReportDispatch, useRefreshEnrichments } from './ReportContext'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { LinkedText } from '@/components/shared/LinkedText'
import { ConfirmDialog } from '@/components/shared/ConfirmDialog'
import { Trash2, MessageSquare } from 'lucide-react'
import type { Comment } from '@/types'

/* ------------------------------------------------------------------ */
/*  Enrichment status badge colors                                     */
/* ------------------------------------------------------------------ */

function enrichmentBadgeVariant(status: string): 'success' | 'destructive' | 'default' {
  const s = status.toLowerCase()
  if (s === 'merged' || s === 'open') return 'success'
  if (s === 'closed') return 'destructive'
  return 'default'
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

interface CommentsSectionProps {
  jobId: string
  testNames: string[]
  childJobName?: string
  childBuildNumber?: number
}

export function CommentsSection({ jobId, testNames, childJobName, childBuildNumber }: CommentsSectionProps) {
  const scopedChildJobName = childJobName ?? ''
  const scopedChildBuildNumber = childBuildNumber ?? 0

  const { comments, enrichments } = useReportState()
  const dispatch = useReportDispatch()
  const refreshEnrichments = useRefreshEnrichments()
  const [text, setText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [succeededTestNames, setSucceededTestNames] = useState<Set<string>>(new Set())
  const draftActiveRef = useRef(false)
  const username = getUsername()

  /** Centralized draft-count state machine: syncs draftActiveRef with the global count. */
  const syncDraftActive = (hasContent: boolean) => {
    if (hasContent && !draftActiveRef.current) {
      draftActiveRef.current = true
      dispatch({ type: 'INCREMENT_DRAFT_COUNT' })
    } else if (!hasContent && draftActiveRef.current) {
      draftActiveRef.current = false
      dispatch({ type: 'DECREMENT_DRAFT_COUNT' })
    }
  }

  // Sync draft-active state whenever text changes (including after submit clears it).
  // This replaces the previous side-effect inside the setText updater, keeping updaters pure.
  useEffect(() => {
    syncDraftActive(text.trim().length > 0)
  }, [text]) // eslint-disable-line react-hooks/exhaustive-deps -- syncDraftActive is stable via ref

  // Ensure the draft count is decremented if this editor unmounts while active.
  useEffect(() => {
    return () => {
      if (draftActiveRef.current) {
        dispatch({ type: 'DECREMENT_DRAFT_COUNT' })
      }
    }
  }, [dispatch])

  // Reset retry tracking when scope or draft content changes
  useEffect(() => {
    setSucceededTestNames(new Set())
  }, [jobId, testNames.join(','), scopedChildJobName, scopedChildBuildNumber, text]) // eslint-disable-line react-hooks/exhaustive-deps -- join produces a stable string key

  const testComments = comments.filter((c) => isCommentInScope(c, testNames, scopedChildJobName, scopedChildBuildNumber))

  async function handleSubmit() {
    if (submitting) return
    const submittedDraft = text
    const submittedText = submittedDraft.trim()
    if (!submittedText) return
    let pendingTestNames = testNames.filter((t) => !succeededTestNames.has(t))
    if (pendingTestNames.length === 0) {
      setSucceededTestNames(new Set())
      pendingTestNames = testNames
    }
    setSubmitting(true)
    setSubmitError(null)
    try {
      const results = await Promise.allSettled(
        pendingTestNames.map((testName) =>
          api.post<{ id: number }>(`/results/${jobId}/comments`, {
            test_name: testName,
            comment: submittedText,
            child_job_name: scopedChildJobName,
            child_build_number: scopedChildBuildNumber,
          }).then((res) => ({ testName, id: res.id }))
        )
      )
      const errors: string[] = []
      let successCount = 0
      results.forEach((result, i) => {
        if (result.status === 'fulfilled') {
          successCount++
          const { testName, id } = result.value
          setSucceededTestNames((prev) => new Set(prev).add(testName))
          const fresh: Comment = {
            id,
            job_id: jobId,
            test_name: testName,
            child_job_name: scopedChildJobName,
            child_build_number: scopedChildBuildNumber,
            comment: submittedText,
            username,
            created_at: new Date().toISOString(),
          }
          dispatch({ type: 'ADD_COMMENT', payload: fresh })
        } else {
          const msg = result.reason instanceof Error ? result.reason.message : 'Failed to post comment'
          errors.push(`${pendingTestNames[i]}: ${msg}`)
        }
      })
      // Refresh enrichments once to pick up any tracker links in new comments
      if (successCount > 0) refreshEnrichments(jobId)
      if (errors.length > 0) {
        const total = pendingTestNames.length
        setSubmitError(`Posted ${successCount}/${total}. Failed: ${errors.join('; ')}`)
      }
      // Clear text only if ALL posts succeeded and the user hasn't changed it during submission
      if (errors.length === 0) {
        setSucceededTestNames(new Set())
        setText((current) => (current === submittedDraft ? '' : current))
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to post comment')
    } finally {
      setSubmitting(false)
    }
  }

  const [deletingIds, setDeletingIds] = useState<Set<number>>(new Set())
  const [deleteTarget, setDeleteTarget] = useState<number | null>(null)

  async function handleDelete(id: number) {
    if (deletingIds.has(id)) return
    setSubmitError(null)
    setDeletingIds((prev) => new Set(prev).add(id))
    try {
      await api.delete(`/results/${jobId}/comments/${id}`)
      dispatch({ type: 'REMOVE_COMMENT', payload: id })
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to delete comment')
    } finally {
      setDeleteTarget(null)
      setDeletingIds((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 text-xs font-display uppercase tracking-widest text-text-tertiary">
        <MessageSquare className="h-3.5 w-3.5" />
        Comments ({testComments.length})
      </div>

      {testComments.length > 0 && (
        <div className="space-y-2">
          {testComments.map((c) => {
            const badges = enrichments[String(c.id)] ?? []

            return (
              <div
                key={c.id}
                className="group flex items-start gap-3 rounded-md bg-surface-elevated/50 px-3 py-2 text-sm animate-slide-up"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-signal-blue">{c.username || 'anon'}</span>
                    <span className="text-[10px] text-text-tertiary">
                      {formatTimestamp(c.created_at)}
                    </span>
                  </div>
                  <p className="mt-1 whitespace-pre-wrap text-text-secondary">
                    <LinkedText
                      text={c.comment}
                      repoUrls={[]}
                      renderLink={(seg, i) => {
                        const match = badges.find((b) => seg.text === b.key || seg.href === b.key)
                        return (
                          <span key={i} className="inline-flex items-center gap-1">
                            <a href={seg.href} target="_blank" rel="noopener noreferrer" className="text-text-link hover:underline">
                              {seg.text}
                            </a>
                            {match && (
                              <Badge variant={enrichmentBadgeVariant(match.status)} className="text-[10px] align-middle">
                                {match.status}
                              </Badge>
                            )}
                          </span>
                        )
                      }}
                    />
                  </p>
                </div>
                {username && c.username === username && (
                  <button
                    type="button"
                    aria-label="Delete comment"
                    onClick={() => setDeleteTarget(c.id)}
                    disabled={deletingIds.has(c.id)}
                    className="shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-signal-blue disabled:opacity-50"
                    title="Delete comment"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-text-tertiary hover:text-signal-red" />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}

      <div className="space-y-1">
        <div className="flex gap-2">
          <Textarea
            aria-label="Add a comment"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Add a comment..."
            className="min-h-[36px] resize-none text-sm"
            rows={1}
            onKeyDown={(e) => {
              if (e.nativeEvent.isComposing) return
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleSubmit()
              }
            }}
          />
          <Button size="sm" onClick={handleSubmit} disabled={!text.trim() || submitting} className="shrink-0">
            Post
          </Button>
        </div>
        {submitError && (
          <span role="alert" className="text-signal-red text-xs">
            {submitError}
          </span>
        )}
      </div>

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}
        title="Delete comment"
        description="Are you sure you want to delete this comment? This action cannot be undone."
        confirmLabel="Delete"
        variant="destructive"
        onConfirm={() => { if (deleteTarget !== null) handleDelete(deleteTarget) }}
        loading={deleteTarget !== null && deletingIds.has(deleteTarget)}
      />
    </div>
  )
}
