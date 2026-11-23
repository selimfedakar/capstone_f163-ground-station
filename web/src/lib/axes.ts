// Axis ranges and ticks for the plots.

export interface PlotRange {
  min: number
  max: number
  ticks: number[]
  digits: number
  mark?: { y: number; color: string }
}

export interface XAxis {
  x0: number
  x1: number
  ticks: number[]
  label: (x: number) => string
}

/** Ticks and labels for an elapsed-time axis of the given length in seconds. */
export function timeAxis(span: number): XAxis {
  const x1 = Math.max(1, span)
  const step = x1 > 300 ? 120 : x1 > 120 ? 60 : x1 > 40 ? 15 : 5
  const ticks: number[] = []
  for (let x = 0; x <= x1; x += step) ticks.push(x)
  return {
    x0: 0,
    x1,
    ticks,
    label: (x: number) =>
      x >= 60 ? `${Math.floor(x / 60)}:${String(Math.round(x % 60)).padStart(2, '0')}` : `${x} s`,
  }
}

/** A y range with round ticks that covers the given values. */
export function fitRange(values: number[], digits = 1, mark?: PlotRange['mark']): PlotRange {
  const finite = values.filter((v) => Number.isFinite(v))
  if (finite.length === 0) return { min: 0, max: 1, ticks: [0, 0.5, 1], digits, mark }
  let lo = Math.min(...finite)
  let hi = Math.max(...finite)
  if (hi - lo < 1e-6) {
    lo -= 0.5
    hi += 0.5
  }
  const raw = (hi - lo) / 4
  const pow = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * pow).find((s) => s >= raw) ?? raw
  const min = Math.floor(lo / step) * step
  const max = Math.ceil(hi / step) * step
  const ticks: number[] = []
  for (let v = min; v <= max + step / 2; v += step) ticks.push(Number(v.toFixed(6)))
  return { min, max, ticks, digits, mark }
}
