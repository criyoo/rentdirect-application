const REFUNDABLE_SECURITY_RATE = 0.1
const ADMINISTRATION_FEE_RATE = 0.1

function roundCurrency(value: number): number
{
    return Math.round((value + Number.EPSILON) * 100) / 100
}

export function calculateRentBreakdown(annualRent: number, paidAmount = 0)
{
    const normalizedAnnualRent = Number(annualRent || 0)
    const normalizedPaidAmount = Number(paidAmount || 0)
    const refundableSecurityDeposit = roundCurrency(normalizedAnnualRent * REFUNDABLE_SECURITY_RATE)
    const administrationFee = roundCurrency(normalizedAnnualRent * ADMINISTRATION_FEE_RATE)
    const depositAmount = roundCurrency(refundableSecurityDeposit + administrationFee)
    const totalAmount = roundCurrency(normalizedAnnualRent + depositAmount)
    const remainingBalance = roundCurrency(Math.max(totalAmount - normalizedPaidAmount, 0))

    return {
        annualRent: roundCurrency(normalizedAnnualRent),
        refundableSecurityDeposit,
        administrationFee,
        depositAmount,
        totalAmount,
        paidAmount: roundCurrency(normalizedPaidAmount),
        remainingBalance,
    }
}
