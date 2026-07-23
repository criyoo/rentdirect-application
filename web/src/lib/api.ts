import axios from 'axios'

export function getApiUrl(): string {
  const configured = import.meta.env.VITE_API_URL
  if (configured) return configured.replace(/\/$/, '')
  if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    return 'http://localhost:8600/api/v1'
  }
  if (window.location.hostname === 'development.rentdirect.homes') {
    return 'https://api.development.rentdirect.homes/api/v1'
  }
  if (window.location.hostname === 'www.rentdirect.homes' || window.location.hostname === 'rentdirect.homes') {
    return 'https://api.rentdirect.homes/api/v1'
  }
  return 'https://api.rentdirect.homes/api/v1'
}

export function getMediaBaseUrl(): string {
  const configured = import.meta.env.VITE_MEDIA_URL
  if (configured) return configured.replace(/\/$/, '')
  if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
    return 'http://localhost:8600/uploads'
  }
  if (window.location.hostname === 'development.rentdirect.homes') {
    return 'https://media.development.rentdirect.homes'
  }
  if (window.location.hostname === 'www.rentdirect.homes' || window.location.hostname === 'rentdirect.homes') {
    return 'https://media.rentdirect.homes'
  }
  return getApiUrl().replace(/\/api\/v1$/, '')
}

export function getWebSocketUrl(path: string): string {
  const configured = import.meta.env.VITE_WS_URL
  if (configured) {
    return `${configured.replace(/\/$/, '')}${path.startsWith('/') ? path : `/${path}`}`
  }
  const apiBase = getApiUrl().replace(/\/api\/v1$/, '')
  const wsBase = apiBase.replace(/^https:/, 'wss:').replace(/^http:/, 'ws:')
  return `${wsBase}${path.startsWith('/') ? path : `/${path}`}`
}

export const api = axios.create({
  baseURL: getApiUrl(),
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

export function resolveMediaUrl(value?: string | null): string {
  if (!value) return '/placeholder.jpg'
  const normalized = value.trim()
  if (!normalized) return '/placeholder.jpg'
  if (normalized.startsWith('http://') || normalized.startsWith('https://')) return normalized

  const path = normalized.startsWith('/') ? normalized : `/${normalized}`
  if (path.startsWith('/uploads/') || path.startsWith('/media/')) {
    return `${getApiUrl().replace(/\/api\/v1$/, '')}${path}`
  }

  return `${getMediaBaseUrl()}${path}`
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const requestUrl = typeof error.config?.url === 'string' ? error.config.url : ''
    const isRefreshRequest = requestUrl.includes('/auth/refresh')
    const isSessionRestoreRequest = requestUrl.includes('/users/me')
    const hasStoredUser = Boolean(localStorage.getItem('user'))

    if (
      error.response?.status === 401 &&
      !error.config?._retry &&
      !isRefreshRequest &&
      (!isSessionRestoreRequest || hasStoredUser)
    ) {
      error.config._retry = true
      try {
        await axios.post(`${getApiUrl()}/auth/refresh`, {}, { withCredentials: true })
        return api(error.config)
      } catch {
        localStorage.removeItem('user')
      }
    }
    return Promise.reject(error)
  },
)
