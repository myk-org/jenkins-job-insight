import { useCallback, useEffect, useState } from 'react'
import { api } from '@/lib/api'
import type { JobMetadata } from '@/types'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { X } from 'lucide-react'

const ALL_VALUE = '__ALL__'

interface MetadataFilterBarProps {
  team: string
  tier: string
  version: string
  labels: string[]
  onTeamChange: (value: string) => void
  onTierChange: (value: string) => void
  onVersionChange: (value: string) => void
  onLabelsChange: (value: string[]) => void
  onClearAll?: () => void
}

export function MetadataFilterBar({
  team,
  tier,
  version,
  labels,
  onTeamChange,
  onTierChange,
  onVersionChange,
  onLabelsChange,
  onClearAll,
}: MetadataFilterBarProps) {
  const [options, setOptions] = useState<{
    teams: string[]
    tiers: string[]
    versions: string[]
    allLabels: string[]
  }>({ teams: [], tiers: [], versions: [], allLabels: [] })

  useEffect(() => {
    let cancelled = false
    api.get<JobMetadata[]>('/api/jobs/metadata').then((data) => {
      if (cancelled) return
      const teams = new Set<string>()
      const tiers = new Set<string>()
      const versions = new Set<string>()
      const allLabels = new Set<string>()
      for (const m of data) {
        if (m.team) teams.add(m.team)
        if (m.tier != null) tiers.add(String(m.tier))
        if (m.version) versions.add(m.version)
        for (const l of m.labels) allLabels.add(l)
      }
      setOptions({
        teams: [...teams].sort(),
        tiers: [...tiers].sort(),
        versions: [...versions].sort(),
        allLabels: [...allLabels].sort(),
      })
    }).catch(() => { /* swallow - filter options are best-effort */ })
    return () => { cancelled = true }
  }, [])

  const hasFilters = team || tier || version || labels.length > 0

  const clearAll = useCallback(() => {
    if (onClearAll) {
      onClearAll()
    } else {
      onTeamChange('')
      onTierChange('')
      onVersionChange('')
      onLabelsChange([])
    }
  }, [onClearAll, onTeamChange, onTierChange, onVersionChange, onLabelsChange])

  const toggleLabel = useCallback((label: string) => {
    if (labels.includes(label)) {
      onLabelsChange(labels.filter((l) => l !== label))
    } else {
      onLabelsChange([...labels, label])
    }
  }, [labels, onLabelsChange])

  // Don't render if no metadata options exist
  const noMetadataOptions =
    options.teams.length === 0 &&
    options.tiers.length === 0 &&
    options.versions.length === 0 &&
    options.allLabels.length === 0

  if (!hasFilters && noMetadataOptions) {
    return null
  }

  const selectFilters = [
    { key: 'team', value: team, options: options.teams, allLabel: 'All teams', aria: 'Filter by team', onChange: onTeamChange },
    { key: 'tier', value: tier, options: options.tiers, allLabel: 'All tiers', aria: 'Filter by tier', onChange: onTierChange },
    { key: 'version', value: version, options: options.versions, allLabel: 'All versions', aria: 'Filter by version', onChange: onVersionChange },
  ]

  return (
    <div className="flex flex-wrap items-center gap-2">
      {selectFilters.filter((f) => f.options.length > 0).map((f) => (
        <Select key={f.key} value={f.value || ALL_VALUE} onValueChange={(v) => f.onChange(v === ALL_VALUE ? '' : v)}>
          <SelectTrigger aria-label={f.aria} className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>{f.allLabel}</SelectItem>
            {f.options.map((option) => (
              <SelectItem key={option} value={option}>{option}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      ))}

      {options.allLabels.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          {options.allLabels.map((label) => (
            <button
              type="button"
              key={label}
              aria-pressed={labels.includes(label)}
              className={`cursor-pointer text-xs px-2 py-0.5 rounded-md border transition-colors ${
                labels.includes(label)
                  ? 'bg-signal-green/20 text-signal-green border-signal-green/40 hover:bg-signal-green/30'
                  : 'border-border-muted text-text-tertiary hover:bg-surface-hover hover:text-text-secondary'
              }`}
              onClick={() => toggleLabel(label)}
            >
              {label}
            </button>
          ))}
        </div>
      )}

      {hasFilters && (
        <Button variant="ghost" size="sm" onClick={clearAll} className="h-7 px-2 text-xs text-text-tertiary hover:text-text-secondary">
          <X className="h-3 w-3 mr-1" />
          Clear filters
        </Button>
      )}
    </div>
  )
}
