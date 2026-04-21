import { useEffect, useRef, useState } from 'react'

export function useClipboard(resetMs = 2000) {
  const [copiedKey, setCopiedKey] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current) }, [])

  const copy = (text: string, key = 'default') => {
    if (!navigator.clipboard?.writeText) return
    void navigator.clipboard.writeText(text)
      .then(() => {
        setCopiedKey(key)
        if (timerRef.current) clearTimeout(timerRef.current)
        timerRef.current = setTimeout(() => setCopiedKey(null), resetMs)
      })
      .catch(() => setCopiedKey(null))
  }

  return { copiedKey, isCopied: (k = 'default') => copiedKey === k, copy }
}
