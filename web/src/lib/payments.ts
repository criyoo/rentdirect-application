export type FlutterwaveInlineCheckout = {
  client_id: string
  tx_ref: string
  amount: number
  currency: string
  redirect_url: string
  payment_options?: string
  customer: {
    email: string
    name: string
    phone_number?: string
  }
  customizations?: {
    title?: string
    description?: string
    logo?: string
  }
  meta?: Record<string, string>
}

export type HostedCheckoutPayload = {
  authorization_url?: string
  checkout_url?: string
  redirect_url?: string
  checkout_mode?: 'inline' | 'virtual_account'
  flutterwave?: FlutterwaveInlineCheckout
  reference?: string
  amount?: number
  currency?: string
  virtual_account?: {
    reference?: string
    account_number?: string
    bank_name?: string
    bank_code?: string
    expires_at?: string | null
  }
} | null | undefined

declare global {
  interface Window {
    FlutterwaveCheckout?: (
      options: Omit<FlutterwaveInlineCheckout, 'client_id'> & { public_key: string; onclose?: () => void },
    ) => void
  }
}

let flutterwaveScriptPromise: Promise<void> | null = null

function resolveHostedCheckoutUrl(checkout: HostedCheckoutPayload) {
  return checkout?.authorization_url ?? checkout?.checkout_url ?? checkout?.redirect_url ?? null
}

function isFlutterwaveInlineCheckout(checkout: HostedCheckoutPayload): checkout is {
  checkout_mode?: 'inline' | 'virtual_account'
  flutterwave: FlutterwaveInlineCheckout
} {
  return (
    Boolean(checkout?.flutterwave?.client_id) &&
    Boolean(checkout?.flutterwave?.tx_ref)
  )
}

function ensureFlutterwaveScript() {
  if (typeof window === 'undefined') {
    return Promise.reject(new Error('Checkout is only available in the browser.'))
  }
  if (typeof window.FlutterwaveCheckout === 'function') {
    return Promise.resolve()
  }
  if (flutterwaveScriptPromise) {
    return flutterwaveScriptPromise
  }

  flutterwaveScriptPromise = new Promise<void>((resolve, reject) => {
    const existingScript = document.querySelector<HTMLScriptElement>('script[data-flutterwave-checkout="true"]')
    if (existingScript) {
      existingScript.remove()
    }

    const script = document.createElement('script')
    script.src = 'https://checkout.flutterwave.com/v3.js'
    script.async = true
    script.dataset.flutterwaveCheckout = 'true'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Unable to load Flutterwave checkout.'))
    document.head.appendChild(script)
  }).catch((error) => {
    flutterwaveScriptPromise = null
    throw error
  })

  return flutterwaveScriptPromise
}

export async function launchHostedCheckout(checkout: HostedCheckoutPayload) {
  if (isFlutterwaveInlineCheckout(checkout)) {
    await ensureFlutterwaveScript()
    if (typeof window.FlutterwaveCheckout !== 'function') {
      throw new Error('Flutterwave checkout is unavailable right now.')
    }
    window.FlutterwaveCheckout({
      amount: checkout.flutterwave.amount,
      currency: checkout.flutterwave.currency,
      customer: checkout.flutterwave.customer,
      customizations: checkout.flutterwave.customizations,
      meta: checkout.flutterwave.meta,
      payment_options: checkout.flutterwave.payment_options,
      public_key: checkout.flutterwave.client_id,
      redirect_url: checkout.flutterwave.redirect_url,
      tx_ref: checkout.flutterwave.tx_ref,
      onclose: () => undefined,
    })
    return true
  }

  const url = resolveHostedCheckoutUrl(checkout)
  if (!url) {
    return false
  }
  window.location.assign(url)
  return true
}
