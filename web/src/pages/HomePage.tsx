import { Link } from 'react-router-dom'

import {
  Container,
  EmptyPanel,
  ErrorPanel,
  Freshness,
  LoadingPanel,
  RouteBadge,
  SectionTitle,
  SeverityBadge,
  SeverityBar,
} from '@/components/common'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { RankedRoute, Route } from '@/lib/api'
import { describeDelay, formatCount, formatPercent, modeName, routeName } from '@/lib/format'
import { useRankings, useRouteLookup, useSystemLive } from '@/lib/queries'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// Lines need at least this many observed arrivals in the past 24 hours to appear on the home page.
const HOME_MIN_ARRIVALS = 50

// A short ranked list of lines (most or least reliable) with each line's on-time share, linking
// to the line's page.
function RankedList({
  title,
  routes,
  lookup,
}: {
  title: string
  routes: RankedRoute[]
  lookup: Map<string, Route>
}) {
  return (
    <section className="rounded-md border border-border bg-card p-5">
      <h3 className="font-display text-xl font-bold uppercase tracking-wide">{title}</h3>
      <ol className="mt-3 divide-y divide-border">
        {routes.map((ranked) => {
          const route = lookup.get(ranked.route_id)
          return (
            <li key={ranked.route_id}>
              <Link
                to={`/lines/${encodeURIComponent(ranked.route_id)}`}
                className="-mx-2 flex items-center gap-3 rounded-sm px-2 py-2.5 hover:bg-muted"
              >
                <RouteBadge route={route} routeId={ranked.route_id} />
                <span className="min-w-0 flex-1 truncate">
                  {routeName(route, ranked.route_long_name ?? ranked.route_id)}
                </span>
                <span className="font-mono text-sm">{formatPercent(ranked.on_time_percentage)}</span>
              </Link>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

// The home page. It says what Linecheck does, then shows the live state of the whole network
// (vehicles reporting, how late they are, split by mode) and the most and least reliable lines of
// the past 24 hours. Every number comes from the API.
export function HomePage() {
  useDocumentTitle(null)
  const live = useSystemLive()
  const rankings = useRankings({ metric: 'on_time', days: 1, minSamples: HOME_MIN_ARRIVALS })
  const lookup = useRouteLookup()
  const ranked = rankings.data?.routes ?? []
  const mostReliable = ranked.slice(0, 5)
  const leastReliable = ranked.length > 5 ? ranked.slice(-5).reverse() : []

  return (
    <Container>
      <section className="grid gap-8 border-b border-border py-10 lg:grid-cols-[1.15fr_1fr] lg:items-start lg:py-14">
        <div>
          <h1 className="font-display text-5xl font-bold uppercase leading-[0.95] tracking-wide sm:text-6xl">
            Live and historical reliability for every MBTA line
          </h1>
          <p className="mt-5 max-w-xl text-lg text-muted-foreground">
            Linecheck compares where MBTA buses, trains, and ferries are against the published timetable
            every minute, then shows which lines run on time and at what hours they fall behind.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Button asChild>
              <Link to="/lines">Browse lines</Link>
            </Button>
            <Button asChild variant="outline">
              <Link to="/rankings">See rankings</Link>
            </Button>
          </div>
        </div>

        <section aria-labelledby="network-now" className="rounded-md border border-border bg-card p-5">
          <SectionTitle id="network-now">Network right now</SectionTitle>
          <div className="mt-3">
            {live.isPending ? (
              <LoadingPanel label="Loading live network data" />
            ) : live.isError ? (
              <ErrorPanel what="live network data" error={live.error} onRetry={() => void live.refetch()} />
            ) : (
              <div className="space-y-4">
                <p className="flex flex-wrap items-baseline gap-x-3">
                  <span className="font-mono text-5xl font-medium">
                    {formatCount(live.data.summary.vehicle_count)}
                  </span>
                  <span className="text-muted-foreground">
                    vehicles reporting, {formatCount(live.data.summary.vehicles_with_delay)} with a delay
                    estimate
                  </span>
                </p>
                <SeverityBar counts={live.data.summary.severity_counts} />
                <Freshness
                  asOf={live.data.as_of}
                  ageSeconds={live.data.data_age_seconds}
                  stale={live.data.stale}
                />
              </div>
            )}
          </div>
        </section>
      </section>

      <section aria-labelledby="by-mode" className="py-10">
        <SectionTitle id="by-mode">By mode</SectionTitle>
        <p className="mt-1 text-sm text-muted-foreground">
          Vehicles heard from in the last 5 minutes. Median delay only counts vehicles with an estimate.
        </p>
        <div className="mt-4">
          {live.data ? (
            live.data.modes.length > 0 ? (
              <div className="overflow-x-auto rounded-md border border-border bg-card">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Mode</TableHead>
                      <TableHead className="text-right">Vehicles</TableHead>
                      <TableHead>Median delay</TableHead>
                      <TableHead>Status</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {live.data.modes.map((mode) => (
                      <TableRow key={mode.route_type ?? 'other'}>
                        <TableCell className="font-medium">{modeName(mode.route_type)}</TableCell>
                        <TableCell className="text-right font-mono">
                          {formatCount(mode.vehicle_count)}
                        </TableCell>
                        <TableCell>{describeDelay(mode.median_delay_seconds)}</TableCell>
                        <TableCell>
                          <SeverityBadge severity={mode.severity} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            ) : (
              <EmptyPanel title="No vehicles are reporting right now.">
                MBTA service may be paused overnight, or the background worker is not running.
              </EmptyPanel>
            )
          ) : null}
        </div>
      </section>

      <section aria-labelledby="past-day" className="border-t border-border py-10">
        <SectionTitle id="past-day">Past 24 hours</SectionTitle>
        <p className="mt-1 text-sm text-muted-foreground">
          On-time share by line over the last 24 complete hours. A line needs at least{' '}
          {HOME_MIN_ARRIVALS} observed arrivals to be ranked.
        </p>
        <div className="mt-4">
          {rankings.isPending ? (
            <LoadingPanel label="Loading rankings" />
          ) : rankings.isError ? (
            <ErrorPanel what="rankings" error={rankings.error} onRetry={() => void rankings.refetch()} />
          ) : ranked.length === 0 ? (
            <EmptyPanel title={`No line has ${HOME_MIN_ARRIVALS} observed arrivals in the past 24 hours yet.`}>
              Rankings appear once the background worker has been collecting data for a few hours.
            </EmptyPanel>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              <RankedList title="Most reliable" routes={mostReliable} lookup={lookup} />
              {leastReliable.length > 0 ? (
                <RankedList title="Least reliable" routes={leastReliable} lookup={lookup} />
              ) : null}
            </div>
          )}
        </div>
        <p className="mt-5">
          <Link to="/rankings" className="font-medium underline underline-offset-4">
            All rankings and filters
          </Link>
        </p>
      </section>
    </Container>
  )
}
