import { useState } from 'react'
import { useParams } from 'react-router-dom'

import {
  Container,
  EmptyPanel,
  ErrorPanel,
  LoadingPanel,
  SectionTitle,
  StatTile,
} from '@/components/common'
import { LineHeader, LineNotFound } from '@/components/LineHeader'
import { SegmentedControl } from '@/components/SegmentedControl'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { WeeklyGrid } from '@/components/WeeklyGrid'
import {
  describeDelay,
  formatCount,
  formatCv,
  formatDuration,
  formatPercent,
  readableDate,
  routeName,
  shiftDate,
  todayIn,
} from '@/lib/format'
import type { GridMetric } from '@/lib/grid'
import { useHistoricalRoute, useRegionRoutes } from '@/lib/queries'
import { useRegion } from '@/lib/regions'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

type PeriodChoice = '7' | '30' | '90'
type DirectionChoice = 'both' | '0' | '1'

const GRID_METRICS: { value: GridMetric; label: string }[] = [
  { value: 'on_time', label: 'On time' },
  { value: 'delay', label: 'Typical delay' },
  { value: 'headway', label: 'Even spacing' },
]

// A line's history page: its on-time record over a chosen period as a weekly timetable grid (one
// cell per day of week and hour, in the city's local time), with totals for the whole period above.
export function LineHistoryPage() {
  const region = useRegion()
  const { agency = '', routeId = '' } = useParams()
  const routes = useRegionRoutes(region.slug)
  const route = routes.data?.find(
    (candidate) => candidate.agency === agency && candidate.route_id === routeId,
  )
  const [period, setPeriod] = useState<PeriodChoice>('30')
  const [direction, setDirection] = useState<DirectionChoice>('both')
  const [metric, setMetric] = useState<GridMetric>('on_time')
  const endDate = todayIn(region.timezone)
  const startDate = shiftDate(endDate, -(Number(period) - 1))
  const history = useHistoricalRoute(agency, routeId, {
    startDate,
    endDate,
    directionId: direction === 'both' ? undefined : Number(direction),
  })
  useDocumentTitle(route ? `${routeName(route)} history` : 'Line history')

  if (routes.data && !route) return <LineNotFound region={region} routeId={routeId} />
  const summary = history.data?.summary

  return (
    <Container>
      <LineHeader region={region} agency={agency} route={route} routeId={routeId} />

      <div className="mt-6 flex flex-wrap items-end gap-4">
        <div className="w-44">
          <Label htmlFor="period">Period</Label>
          <Select value={period} onValueChange={(value) => setPeriod(value as PeriodChoice)}>
            <SelectTrigger id="period" className="mt-1.5 w-full bg-card">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">Past 7 days</SelectItem>
              <SelectItem value="30">Past 30 days</SelectItem>
              <SelectItem value="90">Past 90 days</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="w-52">
          <Label htmlFor="history-direction">Direction</Label>
          <Select value={direction} onValueChange={(value) => setDirection(value as DirectionChoice)}>
            <SelectTrigger id="history-direction" className="mt-1.5 w-full bg-card">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="both">Both directions</SelectItem>
              <SelectItem value="0">Direction 0</SelectItem>
              <SelectItem value="1">Direction 1</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
      <p className="mt-3 text-sm text-muted-foreground">
        {readableDate(startDate)} to {readableDate(endDate)}, {region.name} time.
      </p>

      <div className="mt-6">
        {history.isPending ? (
          <LoadingPanel rows={5} label="Loading history" />
        ) : history.isError ? (
          <ErrorPanel what="this line's history" error={history.error} onRetry={() => void history.refetch()} />
        ) : summary && summary.sample_count === 0 && summary.headway_sample_count === 0 ? (
          <EmptyPanel title="No arrivals recorded for this line in this period yet.">
            {region.realtime_configured
              ? 'Hourly statistics appear once the background worker has run for at least an hour while the line is in service.'
              : `Hourly statistics need live ${region.operator} data, which is not connected yet.`}
          </EmptyPanel>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <StatTile
                label="On time"
                value={formatPercent(history.data.summary.on_time_percentage)}
                detail={`From ${formatCount(history.data.summary.sample_count)} observed arrivals`}
              />
              <StatTile
                label="Typical delay"
                value={formatDuration(history.data.summary.avg_abs_delay_seconds)}
                detail={`Average: ${describeDelay(history.data.summary.avg_delay_seconds)}`}
              />
              <StatTile
                label="Average gap between vehicles"
                value={formatDuration(history.data.summary.avg_headway_seconds)}
                detail={`From ${formatCount(history.data.summary.headway_sample_count)} measured gaps`}
              />
              <StatTile
                label="Spacing regularity (CV)"
                value={formatCv(history.data.summary.headway_cv)}
                detail="0 is perfectly even; higher means bunching"
              />
              <StatTile
                label="Extra wait from uneven spacing"
                value={formatDuration(history.data.summary.excess_wait_seconds)}
                detail="Only measured for service every 15 minutes or more often"
              />
            </div>

            <section aria-labelledby="weekly-grid" className="mt-10">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <SectionTitle id="weekly-grid">Week at a glance</SectionTitle>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Each cell combines every matching day and hour in the period.
                  </p>
                </div>
                <SegmentedControl
                  label="Grid shows"
                  options={GRID_METRICS}
                  value={metric}
                  onChange={setMetric}
                />
              </div>
              <div className="mt-4">
                <WeeklyGrid cells={history.data.cells} metric={metric} cityName={region.name} />
              </div>
            </section>
          </>
        )}
      </div>
    </Container>
  )
}
