import type { HistoricalCell } from '@/lib/api'
import { DAY_LABELS, cellReading, GRID_SCALES, hourLabel, type GridMetric } from '@/lib/grid'
import { cn } from '@/lib/utils'

// The weekly timetable card: one row per day (Monday first) and one column per hour, each cell
// colored by the chosen metric for that day and hour across the selected period. It is a real table,
// so screen readers announce the day and hour for each cell; every cell also has a text description
// on hover. Cells with no observations stay blank. On narrow screens the grid scrolls sideways.
// `cityName` names whose local time the days and hours are in, for example "Los Angeles".
export function WeeklyGrid({
  cells,
  metric,
  cityName,
}: {
  cells: HistoricalCell[]
  metric: GridMetric
  cityName: string
}) {
  const byPosition = new Map(cells.map((cell) => [`${cell.day_of_week}-${cell.hour_of_day}`, cell]))
  const scale = GRID_SCALES[metric]

  return (
    <div>
      <div className="overflow-x-auto rounded-md border border-border bg-card">
        <table className="w-full min-w-4xl table-fixed border-collapse text-xs">
          <caption className="sr-only">
            {scale.title} by day of week and hour of day, {cityName} time
          </caption>
          <colgroup>
            <col className="w-20" />
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
            {DAY_LABELS.map((dayName, day) => (
              <tr key={dayName} className="border-t border-border">
                <th
                  scope="row"
                  className="px-2 py-1 text-left font-display text-base font-bold uppercase tracking-wide"
                >
                  {dayName.slice(0, 3)}
                </th>
                {Array.from({ length: 24 }, (_, hour) => {
                  const cell = byPosition.get(`${day}-${hour}`)
                  const reading = cell ? cellReading(cell, metric) : null
                  return (
                    <td key={hour} className="p-0.5">
                      <div
                        title={reading?.description ?? `${dayName} ${hourLabel(hour)}: no data`}
                        className={cn(
                          'flex h-9 items-center justify-center rounded-[3px] font-mono text-[11px]',
                          reading ? reading.className : 'bg-muted/50',
                        )}
                      >
                        {reading ? (
                          <>
                            <span aria-hidden="true">{reading.short}</span>
                            <span className="sr-only">{reading.description}</span>
                          </>
                        ) : (
                          <span className="sr-only">No data</span>
                        )}
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="mt-3 flex flex-wrap gap-x-5 gap-y-2 text-sm" aria-label={`${scale.title} legend`}>
        {scale.steps.map((step) => (
          <li key={step.label} className="flex items-center gap-2">
            <span className={cn('size-3.5 rounded-[3px]', step.className)} aria-hidden="true" />
            {step.label}
          </li>
        ))}
        <li className="flex items-center gap-2">
          <span className="size-3.5 rounded-[3px] bg-muted/50" aria-hidden="true" />
          No data
        </li>
      </ul>
    </div>
  )
}
