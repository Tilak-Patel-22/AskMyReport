import { useRef, useState } from 'react'
import { usePress } from '../../motion'
import s from './Composer.module.css'

type Props = {
  busy: boolean // waiting on an answer or an upload
  placeholder: string
  onSend: (query: string) => void
}

export function Composer({ busy, placeholder, onSend }: Props) {
  const [text, setText] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const sendRef = useRef<HTMLButtonElement>(null)
  usePress(sendRef)
  const query = text.trim()

  return (
    // a native <form> gives "Enter sends" for free
    <form
      className={s.form}
      onSubmit={(e) => {
        e.preventDefault()
        if (!query || busy) return
        onSend(query)
        setText('')
        inputRef.current?.focus()
      }}
    >
      <label htmlFor="question" className="visually-hidden">
        Ask a question
      </label>
      <input
        ref={inputRef}
        id="question"
        className={s.input}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={placeholder}
        autoComplete="off"
        maxLength={500}
      />
      <button ref={sendRef} className={s.send} type="submit" disabled={busy || !query}>
        <svg className={s.icon} viewBox="0 0 24 24" aria-hidden="true">
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
        <span>Send</span>
      </button>
    </form>
  )
}
