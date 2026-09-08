/** Domain services: every backend endpoint wrapped in one place. */
import http, { api, tokenStorage } from '../api/client'

export const authService = {
  async login(username, password) {
    const { data } = await http.post('/auth/login/', { username, password })
    tokenStorage.access = data.access
    tokenStorage.refresh = data.refresh
    return data.user
  },
  async logout() {
    try {
      if (tokenStorage.refresh) await api.post('/auth/logout/', { refresh: tokenStorage.refresh })
    } finally {
      tokenStorage.access = null
      tokenStorage.refresh = null
    }
  },
  profile: () => api.get('/auth/profile/'),
  updateProfile: (payload) => api.patch('/auth/profile/', payload),
  changePassword: (payload) => api.post('/auth/change-password/', payload),
  requestPasswordReset: (email) => api.post('/auth/password-reset/', { email }),
}

export const patientService = {
  list: (params) => api.get('/patients/', { params }),
  create: (payload) => api.post('/patients/create/', payload),
  detail: (id) => api.get(`/patients/${id}/`),
  assignments: () => api.get('/patients/assignments/'),
  createAssignment: (payload) => api.post('/patients/assignments/', payload),
  deleteAssignment: (id) => api.delete(`/patients/assignments/${id}/`),
}

export const assessmentService = {
  create: (payload) => api.post('/assessments/', payload),
  list: (params) => api.get('/assessments/', { params }),
  history: (patientId) => api.get('/assessments/risk-history/', { params: patientId ? { patient: patientId } : {} }),
  trend: (patientId) => api.get('/assessments/risk-trends/', { params: patientId ? { patient: patientId } : {} }),
  alerts: (params) => api.get('/assessments/alerts/', { params }),
  ackAlert: (id, status) => api.post(`/assessments/alerts/${id}/ack/`, { status }),
}

export const modelService = {
  list: () => api.get('/models/'),
  compare: () => api.get('/models/compare/'),
  activate: (id) => api.post(`/models/${id}/activate/`),
  featureImportance: () => api.get('/models/feature-importance/'),
  diagnostics: () => api.get('/models/diagnostics/'),
}

export const chatService = {
  sessions: () => api.get('/chat/sessions/'),
  createSession: (title) => api.post('/chat/sessions/', { title }),
  session: (id) => api.get(`/chat/sessions/${id}/`),
  send: (id, message) => api.post(`/chat/sessions/${id}/send/`, { message }),
  deleteSession: (id) => api.delete(`/chat/sessions/${id}/`),
}

export const kbService = {
  documents: () => api.get('/rag/documents/'),
  upload: (form) => api.post('/rag/documents/', form),
  deleteDocument: (id) => api.delete(`/rag/documents/${id}/`),
  reindex: () => api.post('/rag/reindex/'),
  retrieve: (question) => api.post('/rag/retrieve/', { question }),
  chunks: (id) => api.get(`/rag/documents/${id}/chunks/`),
}

export const reportService = {
  list: (params) => api.get('/reports/', { params }),
  generate: (assessmentId) => api.post('/reports/', { assessment: assessmentId }),
}

export const adminService = {
  stats: () => api.get('/admin/stats/'),
  users: () => api.get('/auth/users/'),
  createUser: (payload) => api.post('/auth/users/', payload),
  updateUser: (id, payload) => api.patch(`/auth/users/${id}/`, payload),
  auditLogs: (params) => api.get('/audit/', { params }),
}
