import type { Source } from '../../api'
import s from './SourceChips.module.css'

type Props = {
  sources: Source[]
  companyName: (id: string) => string
}

export function SourceChips({ sources, companyName }: Props) {
  if (sources.length === 0) return null
  return (
    <div className={s.sources}>
      <span className={s.label} aria-hidden="true">
        Sources
      </span>
      <ul className={s.list} aria-label="Sources">
        {sources.map((src) => (
          <li key={`${src.company}-${src.year}-${src.page_number}`} className={s.chip}>
            {companyName(src.company)} · FY{src.year} · p. {src.page_number}
          </li>
        ))}
      </ul>
    </div>
  )
}
