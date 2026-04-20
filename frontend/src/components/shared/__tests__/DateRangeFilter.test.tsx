import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { DateRangeFilter } from '../DateRangeFilter'

describe('DateRangeFilter', () => {
  it('renders both date inputs', () => {
    render(<DateRangeFilter from="" to="" onFromChange={() => {}} onToChange={() => {}} />)
    expect(screen.getByLabelText('Filter from date')).toBeDefined()
    expect(screen.getByLabelText('Filter to date')).toBeDefined()
  })

  it('calls onFromChange when from date changes', () => {
    const onFromChange = vi.fn()
    render(<DateRangeFilter from="" to="" onFromChange={onFromChange} onToChange={() => {}} />)
    fireEvent.change(screen.getByLabelText('Filter from date'), { target: { value: '2025-01-01' } })
    expect(onFromChange).toHaveBeenCalledWith('2025-01-01')
  })

  it('calls onToChange when to date changes', () => {
    const onToChange = vi.fn()
    render(<DateRangeFilter from="" to="" onFromChange={() => {}} onToChange={onToChange} />)
    fireEvent.change(screen.getByLabelText('Filter to date'), { target: { value: '2025-12-31' } })
    expect(onToChange).toHaveBeenCalledWith('2025-12-31')
  })

  it('does not show clear button when both values are empty', () => {
    render(<DateRangeFilter from="" to="" onFromChange={() => {}} onToChange={() => {}} />)
    expect(screen.queryByLabelText('Clear date filter')).toBeNull()
  })

  it('shows clear button when from is set', () => {
    render(<DateRangeFilter from="2025-01-01" to="" onFromChange={() => {}} onToChange={() => {}} />)
    expect(screen.getByLabelText('Clear date filter')).toBeDefined()
  })

  it('shows clear button when to is set', () => {
    render(<DateRangeFilter from="" to="2025-12-31" onFromChange={() => {}} onToChange={() => {}} />)
    expect(screen.getByLabelText('Clear date filter')).toBeDefined()
  })

  it('clears both values when clear button is clicked', () => {
    const onFromChange = vi.fn()
    const onToChange = vi.fn()
    render(<DateRangeFilter from="2025-01-01" to="2025-12-31" onFromChange={onFromChange} onToChange={onToChange} />)
    fireEvent.click(screen.getByLabelText('Clear date filter'))
    expect(onFromChange).toHaveBeenCalledWith('')
    expect(onToChange).toHaveBeenCalledWith('')
  })

  it('sets max constraint on from input based on to value', () => {
    render(<DateRangeFilter from="" to="2025-06-15" onFromChange={() => {}} onToChange={() => {}} />)
    expect(screen.getByLabelText('Filter from date').getAttribute('max')).toBe('2025-06-15')
  })

  it('sets min constraint on to input based on from value', () => {
    render(<DateRangeFilter from="2025-01-01" to="" onFromChange={() => {}} onToChange={() => {}} />)
    expect(screen.getByLabelText('Filter to date').getAttribute('min')).toBe('2025-01-01')
  })

  it('does not set max on from input when to is empty', () => {
    render(<DateRangeFilter from="" to="" onFromChange={() => {}} onToChange={() => {}} />)
    expect(screen.getByLabelText('Filter from date').getAttribute('max')).toBeNull()
  })

  it('does not set min on to input when from is empty', () => {
    render(<DateRangeFilter from="" to="" onFromChange={() => {}} onToChange={() => {}} />)
    expect(screen.getByLabelText('Filter to date').getAttribute('min')).toBeNull()
  })
})
