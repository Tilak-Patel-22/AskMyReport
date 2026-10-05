import { useRef } from 'react'
import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Chart } from '../../api'
import { useTilt } from '../../motion'
import s from './AnswerChart.module.css'

const number = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }) // 225458 -> 2,25,458 like the reports

export function AnswerChart({ chart }: { chart: Chart }) {
  const figureRef = useRef<HTMLElement>(null)
  useTilt(figureRef, 5) // the chart card lifts and tilts toward the pointer
  const data = chart.labels.map((label, i) => ({ label, value: chart.values[i] }))
  const isBar = chart.chart_type === 'bar'
  const ChartKind = isBar ? BarChart : LineChart
  // the LLM often already names the unit in metric_name ("…(₹ Crore)"); don't print it twice
  const title = chart.metric_name.toLowerCase().includes(chart.unit.toLowerCase())
    ? chart.metric_name
    : `${chart.metric_name} (${chart.unit})`

  return (
    <figure ref={figureRef} className={s.figure}>
      <figcaption className={s.caption}>{title}</figcaption>
      <div className={s.chart}>
        <ResponsiveContainer width="100%" height="100%">
          <ChartKind data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="label" tickLine={false} />
            <YAxis tickFormatter={(v: number) => number.format(v)} tickLine={false} axisLine={false} width={72} />
            <Tooltip
              formatter={(v) => [`${number.format(Number(v))} ${chart.unit}`, chart.metric_name]}
              contentStyle={{
                background: 'var(--color-field)',
                border: 'var(--border-width) solid var(--color-border-strong)',
                borderRadius: 'var(--radius-md)',
              }}
              labelStyle={{ color: 'var(--color-text)' }}
              itemStyle={{ color: 'var(--color-text)' }}
              cursor={isBar ? { fill: 'var(--color-surface-muted)' } : { stroke: 'var(--color-border-strong)' }}
            />
            {/* no draw-in animation: decorative only, and it stalls in background tabs / ignores reduced motion */}
            {isBar ? (
              <Bar dataKey="value" radius={[10, 10, 0, 0]} isAnimationActive={false} />
            ) : (
              <Line dataKey="value" type="monotone" strokeWidth={3} dot={{ r: 4 }} activeDot={{ r: 6 }} isAnimationActive={false} />
            )}
          </ChartKind>
        </ResponsiveContainer>
      </div>
      {/* same numbers as text, for screen readers and anyone who wants exact values */}
      <details className={s.data}>
        <summary>Show data table</summary>
        <table>
          <caption className="visually-hidden">{title}</caption>
          <thead>
            <tr>
              <th scope="col">{isBar ? 'Item' : 'Year'}</th>
              <th scope="col">{chart.unit || 'Value'}</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.label}>
                <th scope="row">{d.label}</th>
                <td>{number.format(d.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  )
}
