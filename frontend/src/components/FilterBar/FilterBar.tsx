import type { Company } from '../../api'
import s from './FilterBar.module.css'

type Props = {
  companies: Company[] | null // null while /companies is loading
  failed: boolean
  company: string // '' = all companies
  year: string // '' = all years
  years: string[] // years available for the current company selection
  onCompanyChange: (company: string) => void
  onYearChange: (year: string) => void
}

export function FilterBar({ companies, failed, company, year, years, onCompanyChange, onYearChange }: Props) {
  const loading = companies === null
  return (
    <div className={s.filters} role="group" aria-label="Filter reports">
      <label className={s.field}>
        <span className={s.label}>Company</span>
        <select
          className={s.select}
          value={company}
          disabled={loading}
          onChange={(e) => onCompanyChange(e.target.value)}
        >
          <option value="">{loading ? 'Loading…' : 'All companies'}</option>
          {companies?.map((c) => (
            <option key={c.company} value={c.company}>
              {c.name}
            </option>
          ))}
        </select>
      </label>
      <label className={s.field}>
        <span className={s.label}>Year</span>
        <select className={s.select} value={year} disabled={loading} onChange={(e) => onYearChange(e.target.value)}>
          <option value="">All years</option>
          {years.map((y) => (
            <option key={y} value={y}>
              FY{y}
            </option>
          ))}
        </select>
      </label>
      {failed && (
        <p className={s.error} role="alert">
          Couldn't load the company list, so questions will search all reports.
        </p>
      )}
    </div>
  )
}
