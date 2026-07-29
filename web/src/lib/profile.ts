import { UserResidence } from '@/types'
import { nigerianStates, stateOfOriginOptions } from '@/lib/locations'

export { nigerianStates, stateOfOriginOptions }

export const MOBILE_INPUT_PATTERN = '^(0[789][0-9]{9}|\\+234[789][0-9]{9})$'
export const MOBILE_INPUT_PLACEHOLDER = '08012345678 or +2348012345678'
export const MOBILE_ERROR_MESSAGE = 'Use 11 digits starting with 07, 08, or 09, or +234 followed by 7, 8, or 9 and 9 more digits.'
export const NIN_INPUT_PATTERN = '^\\d{11}$'
export const NIN_INPUT_PLACEHOLDER = '11 digit NIN'
export const NIN_ERROR_MESSAGE = 'NIN must be exactly 11 digits.'
export const BVN_INPUT_PATTERN = '^\\d{11}$'
export const BVN_INPUT_PLACEHOLDER = '11 digit BVN'
export const BVN_ERROR_MESSAGE = 'BVN must be exactly 11 digits.'
export const CAC_REGISTRATION_INPUT_PATTERN = '^(RC|BN|IT|LP)[0-9]{5,8}$'
export const CAC_REGISTRATION_INPUT_PLACEHOLDER = 'RC1234567'
export const CAC_REGISTRATION_ERROR_MESSAGE = 'CAC registration number must start with RC, BN, IT, or LP followed by 5 to 8 digits.'

const localMobilePattern = /^0[789]\d{9}$/
const internationalMobilePattern = /^\+234[789]\d{9}$/
const ninPattern = /^\d{11}$/
const bvnPattern = /^\d{11}$/
const cacRegistrationPattern = /^(RC|BN|IT|LP)\d{5,8}$/

export function validateMobile(value: string): string | null
{
    const trimmed = value.trim()
    if (!trimmed) return null
    if (localMobilePattern.test(trimmed) || internationalMobilePattern.test(trimmed))
    {
        return null
    }
    return MOBILE_ERROR_MESSAGE
}

export function validateNin(value: string): string | null
{
    const trimmed = value.trim()
    if (!trimmed) return null
    if (ninPattern.test(trimmed))
    {
        return null
    }
    return NIN_ERROR_MESSAGE
}

export function validateBvn(value: string): string | null
{
    const trimmed = value.trim()
    if (!trimmed) return null
    if (bvnPattern.test(trimmed))
    {
        return null
    }
    return BVN_ERROR_MESSAGE
}

export function validateCacRegistrationNumber(value: string): string | null
{
    const trimmed = value.trim().toUpperCase()
    if (!trimmed) return null
    if (cacRegistrationPattern.test(trimmed))
    {
        return null
    }
    return CAC_REGISTRATION_ERROR_MESSAGE
}

export function formatIdentityNumberInput(value: string): string
{
    return value.replace(/\D/g, '').slice(0, 11)
}

export function formatCacRegistrationNumberInput(value: string): string
{
    return value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 10)
}

export function validateResidence(stateOfOrigin: string, residence: UserResidence): Record<string, string>
{
    const errors: Record<string, string> = {}
    const state = residence.state?.trim() || ''
    const city = residence.city?.trim() || ''
    const address = residence.address?.trim() || ''
    const originCountry = residence.origin_country?.trim() || ''
    const originCity = residence.origin_city?.trim() || ''

    const currentResidence = [state, city, address]
    if (currentResidence.some(Boolean) && !currentResidence.every(Boolean))
    {
        errors.residence = 'Residence state, city, and address must all be provided together.'
    }

    if (stateOfOrigin === 'Others')
    {
        if (!originCountry)
        {
            errors.origin_country = 'Country is required when state of origin is Others.'
        }
        if (!originCity)
        {
            errors.origin_city = 'City is required when state of origin is Others.'
        }
    }

    return errors
}
