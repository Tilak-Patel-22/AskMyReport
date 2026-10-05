import gsap from 'gsap'
import { useEffect, useRef, useState } from 'react'
import { reducedMotion, useEnter } from '../../motion'
import s from './WaitIndicator.module.css'

type Props = {
  label: string // what is happening, e.g. "Thinking: reading the reports…"
  hint: string // how long it usually takes
  slowAfter: number // seconds before switching to slowHint
  slowHint: string
}

/** Long-wait feedback (answers ~20–30 s, uploads up to ~1 min): bouncing dots + a ticking timer, never a frozen UI. */
export function WaitIndicator({ label, hint, slowAfter, slowHint }: Props) {
  const [seconds, setSeconds] = useState(0)
  const bubbleRef = useRef<HTMLDivElement>(null)
  const dotsRef = useRef<HTMLSpanElement>(null)
  useEnter(bubbleRef)

  useEffect(() => {
    const timer = setInterval(() => setSeconds((n) => n + 1), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!dotsRef.current || reducedMotion()) return
    const tween = gsap.to(dotsRef.current.children, {
      y: -7,
      rotationY: 180,
      duration: 0.45,
      ease: 'sine.inOut',
      stagger: { each: 0.15, repeat: -1, yoyo: true },
    })
    return () => {
      tween.revert()
    }
  }, [])

  return (
    <li className={s.row}>
      {/* one status message for screen readers; the per-second timer is hidden so it isn't re-announced */}
      <div ref={bubbleRef} className={s.bubble} role="status">
        <span ref={dotsRef} className={s.dots} aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        <span className={s.text}>
          <span>{label}</span>
          <span className={s.hint}>{seconds < slowAfter ? hint : slowHint}</span>
        </span>
        <span className={s.timer} aria-hidden="true">
          {seconds}s
        </span>
      </div>
    </li>
  )
}
