import { UserResidence } from '@/types'
import { nigerianStates, stateOfOriginOptions } from '@/lib/locations'

export { nigerianStates, stateOfOriginOptions }

const localMobilePattern = /^0[789]\d{9}$/
const internationalMobilePattern = /^\+234(70|71|80|81|90|91)\d{7}$/
const ninPattern = /^\d{11}$/

export function validateMobile(value: string): string | null
{
    const trimmed = value.trim()
    if (!trimmed) return null
    if (localMobilePattern.test(trimmed) || internationalMobilePattern.test(trimmed))
    {
        return null
    }
    return 'Use 11 digits starting with 07, 08, or 09, or +234 followed by 70, 71, 80, 81, 90, or 91.'
}

export function validateNin(value: string): string | null
{
    const trimmed = value.trim()
    if (!trimmed) return null
    if (ninPattern.test(trimmed))
    {
        return null
    }
    return 'NIN must be exactly 11 digits.'
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
