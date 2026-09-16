import type { RunHour } from '@/lib/api'
import { hourLabel } from '@/lib/grid'
import { hourReading } from '@/lib/runs'
import { cn } from '@/lib/utils'

// The day a timestamp falls on, in the reader's own time zone, for the row headers.
function dayLabel(iso: string): string {
  return new Intl.DateTimeFormat('en-US', { weekday: 'short', month: 'short', day: 'numeric' }).format(
    new Date(iso),
  )
}

// The hour of the day a timestamp falls in, in the reader's own time zone.
function hourOf(iso: string): number {
  return new Date(iso).getHours()
}

// The day a timestamp belongs to, as a key that groups hours into rows.
function dayKey(iso: string): string {
  const when = new Date(iso)
  return `${when.getFullYear()}-${when.getMonth()}-${when.getDate()}`
}

// Job runs hour by hour: one row per day, one cell per hour, coloured by what happened in that hour.
// It is a real table, so screen readers announce the day and hour of every cell, and each cell
// carries a full sentence including the "no runs recorded" case, which is its own colour rather than
// a blank the reader would have to interpret. On narrow screens it scrolls sideways.
export function RunTimeline({ hours }: { hours: RunHour[] }) {
  const days = new Map<string, RunHour[]>()
  for (const hour of hours) {
    const key = dayKey(hour.hour)
    days.set(key, [...(days.get(key) ?? []), hour])
  }

  return (
    <div>
      <div className="overflow-x-auto rounded-md border border-border bg-card">
        <table className="w-full min-w-4xl table-fixed border-collapse text-xs">
          <caption className="sr-only">Background job runs by day and hour, your local time</caption>
          <colgroup>
            <col className="w-28" />
            {Array.from({ length: 24 }, (_, hour) => (
              <col key={hour} />
            ))}
          </colgroup>
          <thead>
            <tr>
              <th scope="col" className="px-2 py-2 text-left font-medium text-muted-foreground">
                <span className="sr-only">Day</span>
              </th>
              {Array.from({ length: 24 }, (_, hour) => (
                <th
                  key={hour}
                  scope="col"
                  className="px-0 py-2 text-center font-mono font-normal text-muted-foreground"
                >
                  {hourLabel(hour)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...days.entries()].map(([key, dayHours]) => {
              const byHour = new Map(dayHours.map((hour) => [hourOf(hour.hour), hour]))
              return (
                <tr key={key} className="border-t border-border">
                  <th
                    scope="row"
                    className="whitespace-nowrap px-2 py-1 text-left font-display text-base font-bold uppercase tracking-wide"
                  >
                    {dayLabel(dayHours[0].hour)}
                  </th>
                  {Array.from({ length: 24 }, (_, hour) => {
                    const found = byHour.get(hour)
                    const when = `${dayLabel(dayHours[0].hour)} ${hourLabel(hour)}`
                    const reading = found
                      ? hourReading(found, when)
                      : { className: 'bg-muted/50', short: '', description: `${when}: outside the period shown` }
                    return (
                      <td key={hour} className="p-0.5">
                        <div
                          title={reading.description}
                          className={cn(
                            'flex h-9 items-center justify-center rounded-[3px] font-mono text-[11px]',
                            reading.className,
                          )}
                        >
                          <span aria-hidden="true">{reading.short}</span>
                          <span className="sr-only">{reading.description}</span>
                        </div>
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label="Timeline legend">
        {[
          { label: 'All runs succeeded', className: 'bg-severity-on-time' },
          { label: 'Something was missing', className: 'bg-severity-minor' },
          { label: 'Some runs did not finish', className: 'bg-severity-major' },
          { label: 'Every run failed', className: 'bg-severity-severe' },
          { label: 'Skipped, already running', className: 'bg-severity-unknown' },
          { label: 'No runs recorded', className: 'bg-muted/50' },
        ].map((step) => (
          <li key={step.label} className="flex items-center gap-2">
            <span className={cn('size-3.5 rounded-[3px]', step.className)} aria-hidden="true" />
            {step.label}
          </li>
        ))}
      </ul>
    </div>
  )
}
