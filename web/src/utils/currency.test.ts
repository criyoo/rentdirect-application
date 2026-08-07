import { describe, expect, it } from 'vitest'
import { formatCurrency, formatCurrencyWithSymbol } from './currency'

describe('currency formatting', () => {
  it('formats numeric and numeric-string amounts with separators', () => {
    expect(formatCurrency(1250000)).toBe('1,250,000')
    expect(formatCurrency('001250000')).toBe('1,250,000')
  })

  it('returns a safe zero value for invalid amounts', () => {
    expect(formatCurrency('not-a-number')).toBe('₦0')
  })

  it('adds the naira symbol to a formatted amount', () => {
    expect(formatCurrencyWithSymbol(45000)).toBe('₦45,000')
  })
})
