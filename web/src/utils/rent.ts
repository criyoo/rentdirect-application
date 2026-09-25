export interface RentRates {
    refundableCautionFeeRate: number
    administrationFeeRate: number
    administrationFeeVatRate: number
    listingDepositRate: number
}

function roundCurrency(value: number): number {
    return Math.round((value + Number.EPSILON) * 100) / 100
}

export function calculateRentBreakdown(annualRent: number, paidAmount = 0, rates?: RentRates) {
    const normalizedAnnualRent = Number(annualRent || 0)
    const normalizedPaidAmount = Number(paidAmount || 0)
    const refundableCautionFee = roundCurrency(normalizedAnnualRent * (rates?.refundableCautionFeeRate ?? 0))
    const administrationFee = roundCurrency(normalizedAnnualRent * (rates?.administrationFeeRate ?? 0))
    const administrationFeeVat = roundCurrency(administrationFee * (rates?.administrationFeeVatRate ?? 0))
    const depositAmount = roundCurrency(refundableCautionFee + administrationFee + administrationFeeVat)
    const optionalDepositAmount = roundCurrency(normalizedAnnualRent * (rates?.listingDepositRate ?? 0))
    const totalAmount = roundCurrency(normalizedAnnualRent + depositAmount)
    const remainingBalance = roundCurrency(Math.max(totalAmount - normalizedPaidAmount, 0))

    return {
        annualRent: roundCurrency(normalizedAnnualRent),
        refundableCautionFee,
        administrationFee,
        administrationFeeVat,
        depositAmount,
        optionalDepositAmount,
        totalAmount,
        paidAmount: roundCurrency(normalizedPaidAmount),
        remainingBalance,
    }
}
