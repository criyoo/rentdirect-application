type GoogleCodeResponse = {
    code?: string
    error?: string
    error_description?: string
}

type GoogleCodeClient = {
    requestCode: () => void
}

type GoogleIdentity = {
    accounts: {
        oauth2: {
            initCodeClient: (config: {
                client_id: string
                scope: string
                ux_mode: 'popup'
                prompt?: string
                callback: (response: GoogleCodeResponse) => void
                error_callback?: (error: { type?: string }) => void
            }) => GoogleCodeClient
        }
    }
}

declare global {
    interface Window {
        google?: GoogleIdentity
    }
}

let googleIdentityPromise: Promise<GoogleIdentity> | null = null

function loadGoogleIdentity() {
    if (typeof window === 'undefined') {
        return Promise.reject(new Error('Google sign-in is only available in the browser.'))
    }
    if (window.google?.accounts?.oauth2) {
        return Promise.resolve(window.google)
    }
    if (googleIdentityPromise) {
        return googleIdentityPromise
    }

    googleIdentityPromise = new Promise<GoogleIdentity>((resolve, reject) => {
        const existing = document.querySelector<HTMLScriptElement>('script[data-google-identity="true"]')
        if (existing) {
            existing.addEventListener('load', () => {
                if (window.google?.accounts?.oauth2) {
                    resolve(window.google)
                    return
                }
                reject(new Error('Google Identity Services loaded without the OAuth client.'))
            })
            existing.addEventListener('error', () => reject(new Error('Failed to load Google Identity Services.')))
            return
        }

        const script = document.createElement('script')
        script.src = 'https://accounts.google.com/gsi/client'
        script.async = true
        script.defer = true
        script.dataset.googleIdentity = 'true'
        script.onload = () => {
            if (window.google?.accounts?.oauth2) {
                resolve(window.google)
                return
            }
            reject(new Error('Google Identity Services loaded without the OAuth client.'))
        }
        script.onerror = () => reject(new Error('Failed to load Google Identity Services.'))
        document.head.appendChild(script)
    }).catch((error) => {
        googleIdentityPromise = null
        throw error
    })

    return googleIdentityPromise
}

export async function requestGoogleAuthorizationCode(clientId: string): Promise<string> {
    const google = await loadGoogleIdentity()

    return new Promise<string>((resolve, reject) => {
        const codeClient = google.accounts.oauth2.initCodeClient({
            client_id: clientId,
            scope: 'openid email profile',
            ux_mode: 'popup',
            prompt: 'consent select_account',
            callback: (response) => {
                if (response.error) {
                    reject(new Error(response.error_description || response.error))
                    return
                }
                if (!response.code) {
                    reject(new Error('Google authentication did not return an authorization code.'))
                    return
                }
                resolve(response.code)
            },
            error_callback: () => {
                reject(new Error('Google authentication was cancelled or blocked.'))
            },
        })
        codeClient.requestCode()
    })
}
