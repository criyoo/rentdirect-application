import { api } from '@/lib/api'

export async function downloadInspectionPdf(inspectionId: string) {
    const response = await api.get(`/agent-inspections/${inspectionId}/pdf`, {
        responseType: 'blob',
    })
    const blob = new Blob([response.data], { type: 'application/pdf' })
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `inspection-${inspectionId}.pdf`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
}
