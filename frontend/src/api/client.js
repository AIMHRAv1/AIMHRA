/**
 * Centralized API client.
 * - Attaches JWT access token to every request
 * - On 401, tries token refresh once, then logs the user out
 * - Normalizes responses: success envelope {success, data} -> data
 * - Normalizes errors: {success:false, error:{code,message,details}}
 */
import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

const storage = {
  get access() { return localStorage.getItem('aimhra_access') },
  get refresh() { return localStorage.getItem('aimhra_refresh') },
  set access(v) { v ? localStorage.setItem('aimhra_access', v) : localStorage.removeItem('aimhra_access') },
  set refresh(v) { v ? localStorage.setItem('aimhra_refresh', v) : localStorage.removeItem('aimhra_refresh') },
}

export const tokenStorage = storage

const http = axios.create({ baseURL: BASE_URL })

http.interceptors.request.use((config) => {
  if (storage.access) config.headers.Authorization = `Bearer ${storage.access}`
  return config
})

let refreshing = null

http.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { response, config } = error
    if (response?.status === 401 && storage.refresh && !config._retried) {
      config._retried = true
      try {
        refreshing = refreshing || axios.post(`${BASE_URL}/auth/refresh/`, { refresh: storage.refresh })
        const { data } = await refreshing
        refreshing = null
        storage.access = data.access
        config.headers.Authorization = `Bearer ${data.access}`
        return http(config)
      } catch (e) {
        refreshing = null
        storage.access = null
        storage.refresh = null
        window.dispatchEvent(new Event('aimhra:logout'))
        return Promise.reject(apiError(e))
      }
    }
    return Promise.reject(apiError(error))
  },
)

export function apiError(error) {
  const payload = error?.response?.data
  if (payload && payload.error) return payload.error
  if (error?.code === 'ERR_NETWORK') {
    return { code: 'NETWORK_ERROR', message: 'Cannot reach the server. Check your connection.', details: {} }
  }
  return { code: 'UNKNOWN', message: error?.message || 'Something went wrong.', details: {} }
}

/** Unwrap the {success, data} envelope; fall back to the raw body. */
export function unwrap(response) {
  const body = response.data
  return body && typeof body === 'object' && 'data' in body ? body.data : body
}

/** All API calls go through these helpers — never raw axios in components. */
export const api = {
  get: async (url, config) => unwrap(await http.get(url, config)),
  post: async (url, data, config) => unwrap(await http.post(url, data, config)),
  patch: async (url, data, config) => unwrap(await http.patch(url, data, config)),
  put: async (url, data, config) => unwrap(await http.put(url, data, config)),
  delete: async (url, config) => unwrap(await http.delete(url, config)),
  /** File downloads (e.g. report PDFs) need the raw response. */
  getRaw: (url, config) => http.get(url, { responseType: 'blob', ...config }),
}

export default http
