import { describe, expect, it } from 'vitest'
import {
  formatCacRegistrationNumberInput,
  formatIdentityNumberInput,
  validateBvn,
  validateCacRegistrationNumber,
  validateMobile,
  validateNin,
  validateResidence,
  validateWhatsapp,
} from './profile'

describe('profile validation', () => {
  it('accepts valid Nigerian mobile, NIN, and BVN values', () => {
    expect(validateMobile('08012345678')).toBeNull()
    expect(validateMobile('+2348012345678')).toBeNull()
    expect(validateNin('12345678901')).toBeNull()
    expect(validateBvn('10987654321')).toBeNull()
  })

  it('rejects malformed identity and mobile values', () => {
    expect(validateMobile('070123')).not.toBeNull()
    expect(validateNin('123')).not.toBeNull()
    expect(validateBvn('1234567890a')).not.toBeNull()
  })

  it('accepts WhatsApp numbers with international dialling codes', () => {
    expect(validateWhatsapp('08012345678')).toBeNull()
    expect(validateWhatsapp('+2348012345678')).toBeNull()
    expect(validateWhatsapp('+447911123456')).toBeNull()
    expect(validateWhatsapp('+233241234567')).toBeNull()
    expect(validateWhatsapp('447911123456')).not.toBeNull()
    expect(validateWhatsapp('+44')).not.toBeNull()
    expect(validateWhatsapp('070123')).not.toBeNull()
  })

  it('normalizes identity and CAC inputs before validation', () => {
    expect(formatIdentityNumberInput('12-345 abc 678901')).toBe('12345678901')
    expect(formatCacRegistrationNumberInput('rc 123-4567')).toBe('RC1234567')
    expect(validateCacRegistrationNumber('rc1234567')).toBeNull()
  })

  it('requires complete residence and origin details when applicable', () => {
    expect(validateResidence('Lagos', { state: 'Lagos', city: '', address: 'Somewhere' })).toEqual({
      residence: 'Residence state, city, and address must all be provided together.',
    })
    expect(validateResidence('Others', { state: '', city: '', address: '', origin_country: '', origin_city: '' })).toEqual({
      origin_country: 'Country is required when state of origin is Others.',
      origin_city: 'City is required when state of origin is Others.',
    })
  })
})
