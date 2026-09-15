import type { HistoricalCell } from '@/lib/api'
import { formatCv, formatDuration, formatPercent } from '@/lib/format'

export type GridMetric = 'on_time' | 'delay' | 'headway'

export const DAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

interface ScaleStep {
  label: string
  className: string
  // The step applies when the value is at most this (or, for on-time share, at least this).
  bound: number
}

interface GridScale {
  title: string
  // true when bigger values are better (on-time share), false when smaller is better.
  higherIsBetter: boolean
  steps: ScaleStep[]
}

// Five solid color steps per metric, best first. Full class names are written out so Tailwind
// includes them in the build.
export const GRID_SCALES: Record<GridMetric, GridScale> = {
  on_time: {
    title: 'On-time share',
    higherIsBetter: true,
    steps: [
      { label: '90% or more', className: 'bg-severity-on-time text-white', bound: 90 },
      { label: '80 to 90%', className: 'bg-scale-good text-foreground', bound: 80 },
      { label: '70 to 80%', className: 'bg-severity-minor text-foreground', bound: 70 },
      { label: '50 to 70%', className: 'bg-severity-major text-white', bound: 50 },
      { label: 'Under 50%', className: 'bg-severity-severe text-white', bound: -Infinity },
    ],
  },
  delay: {
    title: 'Typical delay',
    higherIsBetter: false,
    steps: [
      { label: 'Within 1 min', className: 'bg-severity-on-time text-white', bound: 60 },
      { label: '1 to 3 min', className: 'bg-scale-good text-foreground', bound: 180 },
      { label: '3 to 5 min', className: 'bg-severity-minor text-foreground', bound: 300 },
      { label: '5 to 10 min', className: 'bg-severity-major text-white', bound: 600 },
      { label: 'Over 10 min', className: 'bg-severity-severe text-white', bound: Infinity },
    ],
  },
  headway: {
    title: 'Headway regularity',
    higherIsBetter: false,
    steps: [
      { label: 'Very even (CV 0.20 or less)', className: 'bg-severity-on-time text-white', bound: 0.2 },
      { label: 'Even (0.20 to 0.35)', className: 'bg-scale-good text-foreground', bound: 0.35 },
      { label: 'Uneven (0.35 to 0.50)', className: 'bg-severity-minor text-foreground', bound: 0.5 },
      { label: 'Bunched (0.50 to 0.75)', className: 'bg-severity-major text-white', bound: 0.75 },
      { label: 'Heavily bunched (over 0.75)', className: 'bg-severity-severe text-white', bound: Infinity },
    ],
  },
}

// Short hour label for the grid header, in the city's local time: "12a", "6a", "12p", "9p".
export function hourLabel(hour: number): string {
  const twelveHour = hour % 12 === 0 ? 12 : hour % 12
  return `${twelveHour}${hour < 12 ? 'a' : 'p'}`
}

// The step of a scale that a value falls into.
function stepFor(scale: GridScale, value: number): ScaleStep {
  const match = scale.steps.find((step) =>
    scale.higherIsBetter ? value >= step.bound : value <= step.bound,
  )
  return match ?? scale.steps[scale.steps.length - 1]
}

// What one grid cell shows for a metric: its color class, a short value that fits in the cell,
// and a full sentence for screen readers and hover text. Null when the cell has no data for it.
export function cellReading(
  cell: HistoricalCell,
  metric: GridMetric,
): { className: string; short: string; description: string } | null {
  const when = `${DAY_LABELS[cell.day_of_week]} ${hourLabel(cell.hour_of_day)}`
  if (metric === 'on_time') {
    if (cell.on_time_percentage === null || cell.sample_count === 0) return null
    return {
      className: stepFor(GRID_SCALES.on_time, cell.on_time_percentage).className,
      short: String(Math.round(cell.on_time_percentage)),
      description: `${when}: ${formatPercent(cell.on_time_percentage)} on time from ${cell.sample_count} arrivals`,
    }
  }
  if (metric === 'delay') {
    if (cell.avg_abs_delay_seconds === null || cell.sample_count === 0) return null
    return {
      className: stepFor(GRID_SCALES.delay, cell.avg_abs_delay_seconds).className,
      short: (cell.avg_abs_delay_seconds / 60).toFixed(1),
      description: `${when}: typical delay ${formatDuration(cell.avg_abs_delay_seconds)} from ${cell.sample_count} arrivals`,
    }
  }
  if (cell.headway_cv === null || cell.headway_sample_count === 0) return null
  return {
    className: stepFor(GRID_SCALES.headway, cell.headway_cv).className,
    short: formatCv(cell.headway_cv).replace(/^0/, ''),
    description: `${when}: headway CV ${formatCv(cell.headway_cv)} from ${cell.headway_sample_count} gaps`,
  }
}
