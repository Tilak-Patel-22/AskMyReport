import gsap from 'gsap'
import { useEffect, type RefObject } from 'react'

// GSAP half of the motion tokens (CSS transitions use --duration-* in styles/tokens.css).
// Curves from ui-ux-pro-max: entrance = "Stagger List" back.out(1.4); hover = power2.out 0.25s.
const ENTER = { duration: 0.45, ease: 'back.out(1.4)' }
const HOVER = { duration: 0.25, ease: 'power2.out' }
const PERSPECTIVE = 900 // px; gives rotateX/Y real depth

export const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

type Ref = RefObject<HTMLElement | null>

/** Entrance: rises, un-tilts (rotateX) and scales into place. `delay` staggers restored history. */
export function useEnter(ref: Ref, delay = 0) {
  useEffect(() => {
    const el = ref.current
    if (!el || reducedMotion()) return
    // perspective is a fixed lens, set once; tweening it (from 900 to none) would warp the card mid-animation
    gsap.set(el, { transformPerspective: PERSPECTIVE, transformOrigin: '50% 100%' })
    const tween = gsap.from(el, { ...ENTER, delay, opacity: 0, y: 18, rotationX: -14, scale: 0.97 })
    return () => {
      tween.revert() // StrictMode re-runs effects; revert so the second run starts clean
    }
  }, [ref, delay])
}

/** 3D tilt + lift that follows the mouse (cards, bubbles, chart). Touch is ignored; leaving resets to flat. */
export function useTilt(ref: Ref, maxDeg = 4) {
  useEffect(() => {
    const el = ref.current
    if (!el || maxDeg === 0 || reducedMotion()) return
    gsap.set(el, { transformPerspective: PERSPECTIVE })
    const rotX = gsap.quickTo(el, 'rotationX', HOVER)
    const rotY = gsap.quickTo(el, 'rotationY', HOVER)
    const lift = gsap.quickTo(el, 'y', HOVER)
    const onMove = (e: PointerEvent) => {
      if (e.pointerType !== 'mouse') return
      const r = el.getBoundingClientRect()
      const x = (e.clientX - r.left) / r.width - 0.5 // -0.5 .. 0.5
      const y = (e.clientY - r.top) / r.height - 0.5
      rotY(x * 2 * maxDeg)
      rotX(-y * 2 * maxDeg)
      lift(-4)
    }
    const onLeave = () => {
      rotX(0)
      rotY(0)
      lift(0)
    }
    el.addEventListener('pointermove', onMove)
    el.addEventListener('pointerleave', onLeave)
    return () => {
      el.removeEventListener('pointermove', onMove)
      el.removeEventListener('pointerleave', onLeave)
      gsap.set(el, { clearProps: 'transform' })
    }
  }, [ref, maxDeg])
}

/** Clay button feel: lifts on hover, squashes on press, springs back on release. */
export function usePress(ref: Ref) {
  useEffect(() => {
    const el = ref.current
    if (!el || reducedMotion()) return
    const to = (vars: gsap.TweenVars) => gsap.to(el, { ...HOVER, overwrite: 'auto', ...vars })
    const enabled = () => !el.matches(':disabled')
    const onEnter = () => enabled() && to({ y: -2, scale: 1.04 })
    const onLeave = () => to({ y: 0, scale: 1 })
    const onDown = () => enabled() && to({ y: 1, scale: 0.95, duration: 0.1 })
    const onUp = () => enabled() && to({ y: -2, scale: 1.04, ease: 'back.out(3)' })
    const events = [
      ['pointerenter', onEnter],
      ['pointerleave', onLeave],
      ['pointerdown', onDown],
      ['pointerup', onUp],
    ] as const
    events.forEach(([name, fn]) => el.addEventListener(name, fn))
    return () => {
      events.forEach(([name, fn]) => el.removeEventListener(name, fn))
      gsap.set(el, { clearProps: 'transform' })
    }
  }, [ref])
}
