import { useEffect, useRef, useState } from 'react'
import { ask, errorMessage, getCompanies, getHistory, uploadPdf, type Company, type Scope } from '../api'
import { ChatMessage, type Message } from '../components/ChatMessage/ChatMessage'
import { Composer } from '../components/Composer/Composer'
import { FilterBar } from '../components/FilterBar/FilterBar'
import { UploadButton, UploadChip } from '../components/Upload/Upload'
import { WaitIndicator } from '../components/WaitIndicator/WaitIndicator'
import { useEnter, useTilt } from '../motion'
import s from './ChatPage.module.css'

const EXAMPLES = [
  "What was HDFC Bank's Gross NPA?",
  'Compare TCS revenue across the years in the report',
  'How much did Reliance spend on CSR?',
]

/** Years offered for a company ('' = all companies), newest first. */
function yearsFor(companies: Company[], company: string): string[] {
  const years = companies.filter((c) => !company || c.company === company).flatMap((c) => c.years)
  return [...new Set(years)].sort().reverse()
}

export function ChatPage() {
  const [companies, setCompanies] = useState<Company[] | null>(null) // null = still loading
  const [companiesFailed, setCompaniesFailed] = useState(false)
  const [company, setCompany] = useState('') // '' = All
  const [year, setYear] = useState('') // '' = All
  const [upload, setUpload] = useState<{ id: string; filename: string } | null>(null) // set = "asking about a PDF" mode
  const [uploading, setUploading] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [pending, setPending] = useState(false)
  const nextId = useRef(0)
  const endRef = useRef<HTMLDivElement>(null)

  const newId = () => nextId.current++
  const add = (m: Message) => setMessages((prev) => [...prev, m])

  useEffect(() => {
    let active = true // StrictMode runs this twice; only the live run may write state (else history doubles)
    getCompanies()
      .then((list) => active && setCompanies(list))
      .catch(() => {
        if (!active) return
        setCompanies([])
        setCompaniesFailed(true)
      })
    // restore this browser's earlier chat; no history (or no endpoint yet) simply means a fresh chat
    getHistory()
      .then((turns) => {
        if (!active || turns.length === 0) return
        const restored = turns.flatMap((t): Message[] => [
          { id: newId(), role: 'user', text: t.query, restored: true },
          { id: newId(), role: 'assistant', answer: t.answer, sources: t.sources ?? [], chart: t.chart ?? null, restored: true },
        ])
        setMessages((prev) => [...restored, ...prev])
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [])

  // keep the newest message (or wait indicator) in view
  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    endRef.current?.scrollIntoView({ block: 'end', behavior: reduce ? 'auto' : 'smooth' })
  }, [messages, pending, uploading])

  const years = yearsFor(companies ?? [], company)
  const names = new Map((companies ?? []).map((c) => [c.company, c.name]))
  const companyName = (id: string) => names.get(id) ?? id

  function changeCompany(next: string) {
    setCompany(next)
    if (year && !yearsFor(companies ?? [], next).includes(year)) setYear('') // that company has no report for it
  }

  async function send(query: string) {
    const scope: Scope = upload ? { upload_id: upload.id } : { company: company || null, year: year || null }
    add({ id: newId(), role: 'user', text: query })
    setPending(true)
    try {
      add({ id: newId(), role: 'assistant', ...(await ask(query, scope)) })
    } catch (err) {
      add({ id: newId(), role: 'error', text: errorMessage(err) })
    } finally {
      setPending(false)
    }
  }

  async function handleFile(file: File) {
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      add({ id: newId(), role: 'error', text: `"${file.name}" isn't a PDF. Please choose a .pdf file.` })
      return
    }
    setUploading(true)
    try {
      const { upload_id } = await uploadPdf(file)
      if (!upload_id) throw new Error('upload response had no upload_id')
      setUpload({ id: upload_id, filename: file.name })
      add({ id: newId(), role: 'notice', text: `Now answering from ${file.name}` })
    } catch (err) {
      add({ id: newId(), role: 'error', text: errorMessage(err) })
    } finally {
      setUploading(false)
    }
  }

  function clearUpload() {
    setUpload(null)
    add({ id: newId(), role: 'notice', text: 'Back to the company report library' })
  }

  const busy = pending || uploading

  return (
    <div className={s.page}>
      <header className={s.header}>
        <div className={s.headerInner}>
          <div className={s.brand}>
            <svg className={s.logo} viewBox="0 0 32 32" aria-hidden="true">
              <rect className={s.logoBack} x="3" y="8" width="17" height="21" rx="5" />
              <rect className={s.logoFront} x="11" y="3" width="18" height="22" rx="5" />
              <path className={s.logoLines} d="M16 10h8M16 14h8M16 18h5" />
            </svg>
            <div>
              <h1 className={s.title}>AskMyReport</h1>
              <p className={s.subtitle}>Ask company annual reports, or your own PDF.</p>
            </div>
          </div>
          <div className={s.controls}>
            {upload ? (
              <UploadChip filename={upload.filename} onClear={clearUpload} />
            ) : (
              <FilterBar
                companies={companies}
                failed={companiesFailed}
                company={company}
                year={year}
                years={years}
                onCompanyChange={changeCompany}
                onYearChange={setYear}
              />
            )}
            <UploadButton busy={uploading} onFile={handleFile} />
          </div>
        </div>
      </header>

      <main className={s.main}>
        <div className={s.column}>
          {messages.length === 0 && !busy && (
            <section className={s.empty} aria-labelledby="empty-title">
              <h2 id="empty-title" className={s.emptyTitle}>
                What do you want to know?
              </h2>
              <p className={s.emptyText}>
                Pick a company or year above, upload your own PDF, or start with one of these:
              </p>
              <ul className={s.examples}>
                {EXAMPLES.map((q, i) => (
                  <li key={q}>
                    <ExampleCard text={q} delay={i * 0.08} onPick={send} />
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* role="log": screen readers announce each new message as it is added */}
          <ol className={s.log} role="log" aria-label="Conversation">
            {messages.map((m, i) => (
              <ChatMessage
                key={m.id}
                message={m}
                companyName={companyName}
                enterDelay={m.restored ? Math.min(i * 0.05, 0.6) : 0}
              />
            ))}
            {pending && (
              <WaitIndicator
                label={`Thinking: reading ${upload ? upload.filename : 'the reports'} and writing an answer`}
                hint="This usually takes 20–30 seconds."
                slowAfter={30}
                slowHint="Still working. Some questions take a little longer."
              />
            )}
            {uploading && (
              <WaitIndicator
                label="Processing your PDF: reading, chunking and indexing it"
                hint="Small PDFs take seconds; a 300-page report takes 1–3 minutes."
                slowAfter={180}
                slowHint="Still processing. Very large PDFs take a while."
              />
            )}
          </ol>
          <div ref={endRef} />
        </div>
      </main>

      <footer className={s.footer}>
        <div className={s.column}>
          <Composer
            busy={busy}
            placeholder={upload ? `Ask about ${upload.filename}…` : 'Ask about revenue, profit, CSR, NPA…'}
            onSend={send}
          />
        </div>
      </footer>
    </div>
  )
}

/** Starter question card: staggers in, tilts toward the pointer. */
function ExampleCard({ text, delay, onPick }: { text: string; delay: number; onPick: (q: string) => void }) {
  const ref = useRef<HTMLButtonElement>(null)
  useEnter(ref, delay)
  useTilt(ref, 6)
  return (
    <button ref={ref} type="button" className={s.example} onClick={() => onPick(text)}>
      {text}
    </button>
  )
}
