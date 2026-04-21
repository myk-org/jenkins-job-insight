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
import { Badge } from '@/components/ui/badge'
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
        if (m.tier) tiers.add(m.tier)
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
    onTeamChange('')
    onTierChange('')
    onVersionChange('')
    onLabelsChange([])
  }, [onTeamChange, onTierChange, onVersionChange, onLabelsChange])

  const toggleLabel = useCallback((label: string) => {
    if (labels.includes(label)) {
      onLabelsChange(labels.filter((l) => l !== label))
    } else {
      onLabelsChange([...labels, label])
    }
  }, [labels, onLabelsChange])

  // Don't render if no metadata options exist
  if (options.teams.length === 0 && options.tiers.length === 0 && options.versions.length === 0 && options.allLabels.length === 0) {
    return null
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {options.teams.length > 0 && (
        <Select value={team || ALL_VALUE} onValueChange={(v) => onTeamChange(v === ALL_VALUE ? '' : v)}>
          <SelectTrigger aria-label="Filter by team" className="w-32">
            <SelectValue placeholder="Team" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>All teams</SelectItem>
            {options.teams.map((t) => (
              <SelectItem key={t} value={t}>{t}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {options.tiers.length > 0 && (
        <Select value={tier || ALL_VALUE} onValueChange={(v) => onTierChange(v === ALL_VALUE ? '' : v)}>
          <SelectTrigger aria-label="Filter by tier" className="w-32">
            <SelectValue placeholder="Tier" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>All tiers</SelectItem>
            {options.tiers.map((t) => (
              <SelectItem key={t} value={t}>{t}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {options.versions.length > 0 && (
        <Select value={version || ALL_VALUE} onValueChange={(v) => onVersionChange(v === ALL_VALUE ? '' : v)}>
          <SelectTrigger aria-label="Filter by version" className="w-32">
            <SelectValue placeholder="Version" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_VALUE}>All versions</SelectItem>
            {options.versions.map((v) => (
              <SelectItem key={v} value={v}>{v}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}

      {options.allLabels.length > 0 && (
        <div className="flex flex-wrap items-center gap-1">
          {options.allLabels.map((label) => (
            <Badge
              key={label}
              variant={labels.includes(label) ? 'default' : 'outline'}
              className={`cursor-pointer text-xs px-2 py-0.5 transition-colors ${
                labels.includes(label)
                  ? 'bg-signal-green/20 text-signal-green border-signal-green/40 hover:bg-signal-green/30'
                  : 'border-border-muted text-text-tertiary hover:bg-surface-hover hover:text-text-secondary'
              }`}
              onClick={() => toggleLabel(label)}
            >
              {label}
            </Badge>
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
