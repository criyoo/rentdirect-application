import { describe, expect, it } from 'vitest'
import { calculateRentBreakdown } from './rent'

describe('rent breakdown', () => {
  it('calculates the deposit, total, and remaining balance', () => {
    expect(calculateRentBreakdown(1_000_000)).toEqual({
      annualRent: 1_000_000,
      refundableSecurityDeposit: 100_000,
      administrationFee: 100_000,
      administrationFeeVat: 7_500,
      depositAmount: 207_500,
      totalAmount: 1_207_500,
      paidAmount: 0,
      remainingBalance: 1_207_500,
    })
  })

  it('does not return a negative remaining balance', () => {
    const breakdown = calculateRentBreakdown(500_000, 700_000)

    expect(breakdown.paidAmount).toBe(700_000)
    expect(breakdown.remainingBalance).toBe(0)
  })

  it('normalizes missing values to zero', () => {
    expect(calculateRentBreakdown(0)).toEqual({
      annualRent: 0,
      refundableSecurityDeposit: 0,
      administrationFee: 0,
      administrationFeeVat: 0,
      depositAmount: 0,
      totalAmount: 0,
      paidAmount: 0,
      remainingBalance: 0,
    })
  })
})
