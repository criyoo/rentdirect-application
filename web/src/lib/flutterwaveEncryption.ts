type CardDetails = {
  cardNumber: string
  expiryMonth: string
  expiryYear: string
  cvv: string
}

export type EncryptedFlutterwaveCard = {
  encrypted_card_number: string
  encrypted_expiry_month: string
  encrypted_expiry_year: string
  encrypted_cvv: string
  nonce: string
}

const NONCE_CHARACTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
const MIN_CARD_NUMBER_DIGITS = 16
const MAX_CARD_NUMBER_DIGITS = 18

function generateNonce(length = 12) {
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(length))
  return Array.from(bytes, (byte) => NONCE_CHARACTERS[byte % NONCE_CHARACTERS.length]).join('')
}

function base64ToBytes(value: string) {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0))
}

async function encryptAES(data: string, token: string, nonce: string) {
  if (nonce.length !== 12) {
    throw new Error('Flutterwave encryption nonce must be exactly 12 characters.')
  }
  if (!globalThis.crypto?.subtle) {
    throw new Error('Secure browser encryption is unavailable.')
  }

  const key = await globalThis.crypto.subtle.importKey(
    'raw',
    base64ToBytes(token),
    { name: 'AES-GCM' },
    false,
    ['encrypt'],
  )
  const encryptedData = await globalThis.crypto.subtle.encrypt(
    {
      name: 'AES-GCM',
      iv: new TextEncoder().encode(nonce),
    },
    key,
    new TextEncoder().encode(data),
  )

  return btoa(String.fromCharCode(...new Uint8Array(encryptedData)))
}

export function normalizeCardDetails(card: CardDetails) {
  const expiryMonth = card.expiryMonth.replace(/\D/g, '').padStart(2, '0').slice(-2)
  const expiryYearDigits = card.expiryYear.replace(/\D/g, '')
  return {
    cardNumber: card.cardNumber.replace(/\D/g, ''),
    expiryMonth,
    expiryYear: expiryYearDigits.length === 4 ? expiryYearDigits.slice(-2) : expiryYearDigits.slice(-2),
    cvv: card.cvv.replace(/\D/g, ''),
  }
}

export function validateCardDetails(card: CardDetails) {
  const normalized = normalizeCardDetails(card)
  if (normalized.cardNumber.length < MIN_CARD_NUMBER_DIGITS || normalized.cardNumber.length > MAX_CARD_NUMBER_DIGITS) {
    return 'Enter a valid card number.'
  }
  const month = Number(normalized.expiryMonth)
  if (month < 1 || month > 12) {
    return 'Enter a valid expiry month.'
  }
  if (normalized.expiryYear.length !== 2) {
    return 'Enter a valid expiry year.'
  }
  if (normalized.cvv.length < 3 || normalized.cvv.length > 4) {
    return 'Enter a valid CVV.'
  }
  return ''
}

export async function encryptFlutterwaveCard(card: CardDetails, encryptionKey: string): Promise<EncryptedFlutterwaveCard> {
  const validationError = validateCardDetails(card)
  if (validationError) {
    throw new Error(validationError)
  }

  const normalized = normalizeCardDetails(card)
  const nonce = generateNonce()
  return {
    nonce,
    encrypted_card_number: await encryptAES(normalized.cardNumber, encryptionKey, nonce),
    encrypted_expiry_month: await encryptAES(normalized.expiryMonth, encryptionKey, nonce),
    encrypted_expiry_year: await encryptAES(normalized.expiryYear, encryptionKey, nonce),
    encrypted_cvv: await encryptAES(normalized.cvv, encryptionKey, nonce),
  }
}
