import { useRef } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { AskResponse } from '../../api'
import { useEnter, useTilt } from '../../motion'
import { AnswerChart } from '../AnswerChart/AnswerChart'
import { SourceChips } from '../SourceChips/SourceChips'
import s from './ChatMessage.module.css'

export type Message = (
  | { id: number; role: 'user'; text: string }
  | ({ id: number; role: 'assistant' } & AskResponse)
  | { id: number; role: 'error'; text: string }
  | { id: number; role: 'notice'; text: string } // mode changes, e.g. "Now answering from report.pdf"
) & { restored?: boolean } // came from /history (entrance is staggered)

type Props = {
  message: Message
  companyName: (id: string) => string
  enterDelay: number
}

export function ChatMessage({ message, companyName, enterDelay }: Props) {
  switch (message.role) {
    case 'user':
      return <UserBubble text={message.text} enterDelay={enterDelay} />
    case 'assistant':
      return <Answer message={message} companyName={companyName} enterDelay={enterDelay} />
    case 'error':
      return <ErrorBubble text={message.text} enterDelay={enterDelay} />
    case 'notice':
      return <Notice text={message.text} enterDelay={enterDelay} />
  }
}

function UserBubble({ text, enterDelay }: { text: string; enterDelay: number }) {
  const ref = useRef<HTMLParagraphElement>(null)
  useEnter(ref, enterDelay)
  useTilt(ref, 4)
  return (
    <li className={`${s.row} ${s.userRow}`}>
      <p ref={ref} className={s.user}>
        <span className="visually-hidden">You asked: </span>
        {text}
      </p>
    </li>
  )
}

function Answer({ message, companyName, enterDelay }: { message: AskResponse; companyName: (id: string) => string; enterDelay: number }) {
  const ref = useRef<HTMLElement>(null)
  useEnter(ref, enterDelay)
  useTilt(ref, 1.5) // big text card: barely tilts so it stays readable
  return (
    <li className={s.row}>
      <article ref={ref} className={s.answer} aria-label="Answer">
        {/* react-markdown renders the LLM's markdown safely (raw HTML is never rendered) */}
        <div className={s.markdown}>
          <Markdown
            remarkPlugins={[remarkGfm]}
            components={{ table: ({ children }) => <div className={s.tableScroll}><table>{children}</table></div> }}
          >
            {message.answer}
          </Markdown>
        </div>
        {message.chart && <AnswerChart chart={message.chart} />}
        <SourceChips sources={message.sources} companyName={companyName} />
      </article>
    </li>
  )
}

function ErrorBubble({ text, enterDelay }: { text: string; enterDelay: number }) {
  const ref = useRef<HTMLDivElement>(null)
  useEnter(ref, enterDelay)
  return (
    <li className={s.row}>
      <div ref={ref} className={s.error}>
        <svg className={s.icon} viewBox="0 0 24 24" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v5M12 16h.01" />
        </svg>
        <p>
          <strong>Couldn't complete that.</strong> {text}
        </p>
      </div>
    </li>
  )
}

function Notice({ text, enterDelay }: { text: string; enterDelay: number }) {
  const ref = useRef<HTMLParagraphElement>(null)
  useEnter(ref, enterDelay)
  return (
    <li className={`${s.row} ${s.noticeRow}`}>
      <p ref={ref} className={s.notice}>
        {text}
      </p>
    </li>
  )
}
