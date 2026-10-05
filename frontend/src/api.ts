import axios from 'axios'

/** Backend base URL: the only place it is written. */
export const API_BASE = 'http://localhost:8000'

const http = axios.create({ baseURL: API_BASE, timeout: 90_000 }) // answers take ~20 s (comparisons ~30 s); leave headroom
const UPLOAD_TIMEOUT = 180_000 // a large PDF is parsed, chunked and embedded server-side: up to ~1 min

/** One id per browser, kept in localStorage so chat history survives reloads. */
export const SESSION_ID = (() => {
  const key = 'askmyreport.session_id'
  try {
    const saved = localStorage.getItem(key)
    if (saved) return saved
    const id = crypto.randomUUID()
    localStorage.setItem(key, id)
    return id
  } catch {
    return crypto.randomUUID() // storage blocked (private mode): history lasts this tab only
  }
})()

export type Company = { company: string; name: string; years: string[] }
export type Source = { company: string; year: string; page_number: number }
export type Chart = {
  chart_type: 'line' | 'bar'
  metric_name: string
  labels: string[]
  values: number[]
  unit: string
}
export type AskResponse = { answer: string; sources: Source[]; chart: Chart | null }
/** One past turn from GET /history/{session_id}. */
export type HistoryTurn = { query: string } & AskResponse
export type Upload = { upload_id: string }
/** Where /ask looks: one uploaded PDF, or the report library narrowed by company/year (null = all). */
export type Scope = { upload_id: string } | { company: string | null; year: string | null }

export async function getCompanies(): Promise<Company[]> {
  return (await http.get<Company[]>('/companies')).data
}

export async function getHistory(): Promise<HistoryTurn[]> {
  const { data } = await http.get<HistoryTurn[]>(`/history/${SESSION_ID}`)
  return Array.isArray(data) ? data : []
}

export async function uploadPdf(file: File): Promise<Upload> {
  const form = new FormData()
  form.append('file', file)
  return (await http.post<Upload>('/upload', form, { timeout: UPLOAD_TIMEOUT })).data
}

export async function ask(query: string, scope: Scope): Promise<AskResponse> {
  return (await http.post<AskResponse>('/ask', { query, session_id: SESSION_ID, ...scope })).data
}

/** One sentence a user can act on, for any failed request. */
export function errorMessage(err: unknown): string {
  if (axios.isAxiosError<{ detail?: string }>(err)) {
    const status = err.response?.status
    if (status === 400) return err.response?.data?.detail ?? 'That request could not be processed.'
    if (status === 404) return "This feature isn't available on the server yet."
    if (status === 413) return 'That PDF is too large to upload.'
    if (status === 502) return 'The AI service is busy or unavailable right now. Please try again in a minute.'
    if (err.code === 'ECONNABORTED') return 'That took too long. Please try again.'
    if (!err.response) return `Can't reach the server at ${API_BASE}. Is the backend running?`
  }
  return 'Something went wrong. Please try again.'
}
