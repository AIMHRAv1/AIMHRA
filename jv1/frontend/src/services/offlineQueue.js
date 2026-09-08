const DB_NAME = 'aimhra-offline'
const STORE = 'assessments'

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: 'id' })
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

export async function queueAssessment(payload) {
  const db = await openDb()
  const record = { id: crypto.randomUUID(), payload, status: 'pending_sync', created_at: new Date().toISOString() }
  await new Promise((resolve, reject) => {
    const request = db.transaction(STORE, 'readwrite').objectStore(STORE).add(record)
    request.onsuccess = resolve
    request.onerror = () => reject(request.error)
  })
  return record
}

export async function pendingAssessments() {
  const db = await openDb()
  return new Promise((resolve, reject) => {
    const request = db.transaction(STORE).objectStore(STORE).getAll()
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

export async function removeQueuedAssessment(id) {
  const db = await openDb()
  await new Promise((resolve, reject) => {
    const request = db.transaction(STORE, 'readwrite').objectStore(STORE).delete(id)
    request.onsuccess = resolve
    request.onerror = () => reject(request.error)
  })
}

export async function syncQueuedAssessments(createAssessment) {
  const records = await pendingAssessments()
  const synced = []
  for (const record of records) {
    try {
      const result = await createAssessment(record.payload)
      await removeQueuedAssessment(record.id)
      synced.push({ ...record, result })
    } catch (error) {
      if (!error.response) break
    }
  }
  return { remaining: (await pendingAssessments()).length, synced }
}
