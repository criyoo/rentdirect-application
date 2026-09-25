import { describe, expect, it } from 'vitest'
import { calculateRentBreakdown } from './rent'

const RATES = {
  refundableCautionFeeRate: 0.1,
  administrationFeeRate: 0.2,
  administrationFeeVatRate: 0.05,
  listingDepositRate: 0.25,
}

describe('rent breakdown', () => {
  it('calculates the deposit, total, and remaining balance from the given rates', () => {
    expect(calculateRentBreakdown(1_000_000, 0, RATES)).toEqual({
      annualRent: 1_000_000,
      refundableCautionFee: 100_000,
      administrationFee: 200_000,
      administrationFeeVat: 10_000,
      depositAmount: 310_000,
      optionalDepositAmount: 250_000,
      totalAmount: 1_310_000,
      paidAmount: 0,
      remainingBalance: 1_310_000,
    })
  })

  it('does not return a negative remaining balance', () => {
    const breakdown = calculateRentBreakdown(500_000, 700_000, RATES)

    expect(breakdown.paidAmount).toBe(700_000)
    expect(breakdown.remainingBalance).toBe(0)
  })

  it('normalizes missing values to zero', () => {
    expect(calculateRentBreakdown(0, 0, RATES)).toEqual({
      annualRent: 0,
      refundableCautionFee: 0,
      administrationFee: 0,
      administrationFeeVat: 0,
      depositAmount: 0,
      optionalDepositAmount: 0,
      totalAmount: 0,
      paidAmount: 0,
      remainingBalance: 0,
    })
  })
})
