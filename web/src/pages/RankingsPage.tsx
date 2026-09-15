import { Link, useSearchParams } from 'react-router-dom'

import {
  Container,
  EmptyPanel,
  ErrorPanel,
  LoadingPanel,
  PageHeader,
  RealtimeNotConnected,
  RouteBadge,
} from '@/components/common'
import { SegmentedControl } from '@/components/SegmentedControl'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { RankingMetric } from '@/lib/api'
import {
  MODE_ORDER,
  formatCount,
  formatCv,
  formatDuration,
  formatPercent,
  localDateTime,
  modeName,
  routeName,
} from '@/lib/format'
import { routeKey, useRankings, useRouteLookup } from '@/lib/queries'
import { linePath, useRegion } from '@/lib/regions'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { cn } from '@/lib/utils'

const METRICS = ['on_time', 'delay', 'headway'] as const
const PERIODS = ['1', '7', '30', '90'] as const
const MODES = ['all', ...MODE_ORDER.map(String)] as const
const MINIMUMS = ['50', '200', '500'] as const

const METRIC_OPTIONS: { value: RankingMetric; label: string }[] = [
  { value: 'on_time', label: 'On time' },
  { value: 'delay', label: 'Smallest delay' },
  { value: 'headway', label: 'Even spacing' },
]

const PERIOD_LABELS: Record<(typeof PERIODS)[number], string> = {
  '1': 'Past 24 hours',
  '7': 'Past 7 days',
  '30': 'Past 30 days',
  '90': 'Past 90 days',
}

// Use a value from the address bar if it is one of the allowed options, otherwise the default.
function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : fallback
}

// A city's rankings page: lines ordered from most to least reliable over a period, by on-time share,
// smallest delay, or most even spacing, optionally for one mode. The chosen filters are kept in the
// address bar so a particular view can be shared as a link.
export function RankingsPage() {
  const region = useRegion()
  useDocumentTitle(`${region.name} rankings`)
  const [params, setParams] = useSearchParams()
  const metric = pick(params.get('metric'), METRICS, 'on_time')
  const days = pick(params.get('days'), PERIODS, '30')
  const mode = pick(params.get('mode'), MODES, 'all')
  const minimum = pick(params.get('min'), MINIMUMS, '200')
  const lookup = useRouteLookup(region.slug)
  const rankings = useRankings(region.slug, {
    metric,
    days: Number(days),
    minSamples: Number(minimum),
    routeType: mode === 'all' ? undefined : Number(mode),
  })

  // Change one filter in the address bar and keep the others.
  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    next.set(key, value)
    setParams(next, { replace: true })
  }

  const sampleWord = metric === 'headway' ? 'measured gaps between vehicles' : 'observed arrivals'
  const highlight = (column: RankingMetric) => (column === metric ? 'font-semibold' : undefined)

  return (
    <Container>
      <PageHeader
        eyebrow={region.name}
        title="Rankings"
        description={`${region.operator} lines ordered from most to least reliable, using complete hours only and both directions combined.`}
      />

      {!region.realtime_configured ? (
        <div className="mt-6">
          <RealtimeNotConnected operator={region.operator} />
        </div>
      ) : null}

      <div className="mt-6 flex flex-wrap items-end gap-4">
        <div>
          <p className="mb-1.5 text-sm font-medium">Rank by</p>
          <SegmentedControl
            label="Rank by"
            options={METRIC_OPTIONS}
            value={metric}
            onChange={(value) => setFilter('metric', value)}
          />
        </div>
        <div className="w-44">
          <Label htmlFor="rank-period">Period</Label>
          <Select value={days} onValueChange={(value) => setFilter('days', value)}>
            <SelectTrigger id="rank-period" className="mt-1.5 w-full bg-card">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PERIODS.map((value) => (
                <SelectItem key={value} value={value}>
                  {PERIOD_LABELS[value]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="w-44">
          <Label htmlFor="rank-mode">Mode</Label>
          <Select value={mode} onValueChange={(value) => setFilter('mode', value)}>
            <SelectTrigger id="rank-mode" className="mt-1.5 w-full bg-card">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All modes</SelectItem>
              {MODE_ORDER.map((routeType) => (
                <SelectItem key={routeType} value={String(routeType)}>
                  {modeName(routeType)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="w-48">
          <Label htmlFor="rank-minimum">Minimum observations</Label>
          <Select value={minimum} onValueChange={(value) => setFilter('min', value)}>
            <SelectTrigger id="rank-minimum" className="mt-1.5 w-full bg-card">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MINIMUMS.map((value) => (
                <SelectItem key={value} value={value}>
                  At least {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="mt-8">
        {rankings.isPending ? (
          <LoadingPanel rows={8} label="Loading rankings" />
        ) : rankings.isError ? (
          <ErrorPanel what="rankings" error={rankings.error} onRetry={() => void rankings.refetch()} />
        ) : rankings.data.routes.length === 0 ? (
          <EmptyPanel title={`No line has at least ${minimum} ${sampleWord} in this period yet.`}>
            Choose a longer period or a lower minimum. Statistics build up as the background worker keeps
            running.
          </EmptyPanel>
        ) : (
          <>
            <div className="overflow-x-auto rounded-md border border-border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-14 text-right">Rank</TableHead>
                    <TableHead>Line</TableHead>
                    <TableHead className={cn('text-right', highlight('on_time'))}>On time</TableHead>
                    <TableHead className={cn('text-right', highlight('delay'))}>Typical delay</TableHead>
                    <TableHead className={cn('text-right', highlight('headway'))}>Spacing (CV)</TableHead>
                    <TableHead className="text-right">Arrivals</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rankings.data.routes.map((ranked) => {
                    const key = routeKey(ranked.agency, ranked.route_id)
                    const route = lookup.get(key)
                    return (
                      <TableRow key={key}>
                        <TableCell className="text-right font-mono">{ranked.rank}</TableCell>
                        <TableCell>
                          <Link
                            to={`${linePath(region.slug, ranked.agency, ranked.route_id)}/history`}
                            className="flex items-center gap-3 hover:underline hover:underline-offset-4"
                          >
                            <RouteBadge route={route} routeId={ranked.route_id} />
                            <span className="truncate">
                              {routeName(route, ranked.route_long_name ?? ranked.route_id)}
                            </span>
                          </Link>
                        </TableCell>
                        <TableCell className={cn('text-right font-mono', highlight('on_time'))}>
                          {formatPercent(ranked.on_time_percentage)}
                        </TableCell>
                        <TableCell className={cn('text-right font-mono', highlight('delay'))}>
                          {formatDuration(ranked.avg_abs_delay_seconds)}
                        </TableCell>
                        <TableCell className={cn('text-right font-mono', highlight('headway'))}>
                          {formatCv(ranked.headway_cv)}
                        </TableCell>
                        <TableCell className="text-right font-mono">{formatCount(ranked.sample_count)}</TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
            <div className="mt-3 space-y-1 text-sm text-muted-foreground">
              <p>
                Complete hours from {localDateTime(rankings.data.period_start, region.timezone)} to{' '}
                {localDateTime(rankings.data.period_end, region.timezone)}, {region.name} time.
              </p>
              {rankings.data.excluded_routes > 0 ? (
                <p>
                  {formatCount(rankings.data.excluded_routes)}{' '}
                  {rankings.data.excluded_routes === 1 ? 'line was' : 'lines were'} left out for having fewer
                  than {minimum} {sampleWord}.
                </p>
              ) : null}
            </div>
          </>
        )}
      </div>
    </Container>
  )
}
