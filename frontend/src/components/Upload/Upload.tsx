import { useRef } from 'react'
import { usePress } from '../../motion'
import s from './Upload.module.css'

type ButtonProps = {
  busy: boolean // a PDF is being processed
  onFile: (file: File) => void
}

/** "Upload PDF": a styled button that opens the native file picker (keyboard + screen-reader friendly). */
export function UploadButton({ busy, onFile }: ButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)
  usePress(buttonRef)

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        className="visually-hidden"
        tabIndex={-1}
        aria-hidden="true"
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = '' // so picking the same file again still fires
          if (file) onFile(file)
        }}
      />
      <button
        ref={buttonRef}
        type="button"
        className={s.upload}
        disabled={busy}
        aria-busy={busy}
        onClick={() => inputRef.current?.click()}
      >
        <svg className={s.icon} viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 15V4M7 9l5-5 5 5M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
        </svg>
        <span>{busy ? 'Processing…' : 'Upload PDF'}</span>
      </button>
    </>
  )
}

type ChipProps = {
  filename: string
  onClear: () => void
}

/** Shown instead of the Company/Year filters while questions go to one uploaded PDF. */
export function UploadChip({ filename, onClear }: ChipProps) {
  const clearRef = useRef<HTMLButtonElement>(null)
  usePress(clearRef)

  return (
    <div className={s.chip} role="status">
      <svg className={s.icon} viewBox="0 0 24 24" aria-hidden="true">
        <path d="M14 3H7a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7zM14 3v4h4" />
      </svg>
      <span className={s.chipText}>
        <span className={s.chipLabel}>Asking about</span>
        <span className={s.filename} title={filename}>
          {filename}
        </span>
      </span>
      <button ref={clearRef} type="button" className={s.clear} onClick={onClear} aria-label={`Stop asking about ${filename}`}>
        <svg className={s.icon} viewBox="0 0 24 24" aria-hidden="true">
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      </button>
    </div>
  )
}
