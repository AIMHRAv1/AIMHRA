import { reportService } from '../services/auth'

/** Download a report through the authorized API endpoint (blob -> object URL). */
export async function downloadReport(id) {
  const response = await reportService.download(id)
  const blob = new Blob([response.data], { type: 'application/pdf' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `AIMHRA-Report-${id}.pdf`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}