// Canvas plumbing shared by the map and the plots: device-pixel-ratio sizing,
// resize handling, and either a throttled animation loop or draw-on-change.

import { useEffect, useRef } from 'react'

export type Draw = (ctx: CanvasRenderingContext2D, width: number, height: number) => void

/**
 * @param fps  frames per second for a live canvas; 0 redraws only when `draw`
 *             changes or the canvas is resized.
 */
export function useCanvas(draw: Draw, fps: number) {
  const ref = useRef<HTMLCanvasElement>(null)
  const drawRef = useRef(draw)
  useEffect(() => {
    drawRef.current = draw
  }, [draw])

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    let width = 0
    let height = 0
    let raf = 0
    let lastPaint = 0

    const paint = () => {
      if (width === 0 || height === 0) return
      const dpr = window.devicePixelRatio || 1
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, width, height)
      drawRef.current(ctx, width, height)
    }
    const resize = () => {
      const r = canvas.getBoundingClientRect()
      const dpr = window.devicePixelRatio || 1
      width = r.width
      height = r.height
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      paint()
    }
    const ro = new ResizeObserver(resize)
    ro.observe(canvas)
    resize()

    if (fps > 0) {
      const loop = (now: number) => {
        if (now - lastPaint >= 1000 / fps) {
          lastPaint = now
          paint()
        }
        raf = requestAnimationFrame(loop)
      }
      raf = requestAnimationFrame(loop)
    }
    return () => {
      ro.disconnect()
      cancelAnimationFrame(raf)
    }
  }, [fps])

  // Static canvases repaint when their draw function (their data) changes.
  useEffect(() => {
    if (fps > 0) return
    const canvas = ref.current
    const ctx = canvas?.getContext('2d')
    if (!canvas || !ctx) return
    const r = canvas.getBoundingClientRect()
    if (r.width === 0) return
    const dpr = window.devicePixelRatio || 1
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, r.width, r.height)
    draw(ctx, r.width, r.height)
  }, [draw, fps])

  return ref
}
