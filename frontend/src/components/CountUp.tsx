import { useLayoutEffect, useRef } from 'react'

/** Animates towards `value` - for the big numbers. Writes straight to the DOM so the page doesn't re-render every frame. */
export function CountUp({ value, format, ms = 900 }: { value: number; format: (v: number) => string; ms?: number }) {
  const ref = useRef<HTMLSpanElement>(null)
  const shown = useRef(0)

  useLayoutEffect(() => {  // layout effect: the starting number is there before first paint
    const el = ref.current!
    const begin = shown.current
    const draw = (v: number) => {
      shown.current = v
      el.textContent = format(v)
    }
    draw(begin)
    if (begin === value || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      draw(value)
      return
    }
    let start: number | null = null  // first frame, so a slow mount doesn't eat the start of the animation
    let frame = 0
    const tick = (t: number) => {
      start ??= t
      const p = Math.min(1, (t - start) / ms)
      draw(begin + (value - begin) * (1 - Math.pow(1 - p, 4)))
      if (p < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value, format, ms])

  return <span ref={ref} />
}
