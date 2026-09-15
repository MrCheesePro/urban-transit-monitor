import { Link } from 'react-router-dom'

import {
  Container,
  EmptyPanel,
  ErrorPanel,
  Freshness,
  LoadingPanel,
  RealtimeNotConnected,
  RouteBadge,
  SectionTitle,
  SeverityBadge,
  SeverityBar,
} from '@/components/common'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { RankedRoute, Region, Route } from '@/lib/api'
import { describeDelay, formatCount, formatPercent, modeName, routeName } from '@/lib/format'
import { routeKey, useRankings, useRegionLive, useRouteLookup } from '@/lib/queries'
import { linePath, useRegion } from '@/lib/regions'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// Lines need at least this many observed arrivals in the past 24 hours to appear on this page.
const OVERVIEW_MIN_ARRIVALS = 50

// A short ranked list of lines (most or least reliable) with each line's on-time share, linking
// to the line's page.
function RankedList({
  title,
  region,
  routes,
  lookup,
}: {
  title: string
  region: Region
  routes: RankedRoute[]
  lookup: Map<string, Route>
}) {
  return (
    <section className="rounded-md border border-border bg-card p-5">
      <h3 className="font-display text-xl font-bold uppercase tracking-wide">{title}</h3>
      <ol className="mt-3 divide-y divide-border">
        {routes.map((ranked) => {
          const route = lookup.get(routeKey(ranked.agency, ranked.route_id))
          return (
            <li key={routeKey(ranked.agency, ranked.route_id)}>
              <Link
                to={linePath(region.slug, ranked.agency, ranked.route_id)}
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

// A city's overview page. It says what Linecheck shows for this city, then the live state of the
// city's network (vehicles reporting, how late they are, split by mode) and the most and least
// reliable lines of the past 24 hours. When the city's live feeds are not connected it says so
// instead. Every number comes from the API.
export function RegionHomePage() {
  const region = useRegion()
  useDocumentTitle(region.name)
  const connected = region.realtime_configured
  const live = useRegionLive(region.slug, connected)
  const rankings = useRankings(
    region.slug,
    { metric: 'on_time', days: 1, minSamples: OVERVIEW_MIN_ARRIVALS },
    connected,
  )
  const lookup = useRouteLookup(region.slug)
  const ranked = rankings.data?.routes ?? []
  const mostReliable = ranked.slice(0, 5)
  const leastReliable = ranked.length > 5 ? ranked.slice(-5).reverse() : []

  return (
    <Container>
      <section className="grid gap-8 border-b border-border py-10 lg:grid-cols-[1.15fr_1fr] lg:items-start lg:py-14">
        <div>
          <h1 className="font-display text-5xl font-bold uppercase leading-[0.95] tracking-wide sm:text-6xl">
            Live and historical reliability for every {region.operator} line
          </h1>
          <p className="mt-5 max-w-xl text-lg text-muted-foreground">
            Linecheck compares where {region.operator} vehicles in {region.name} are against the published
            timetable every minute, then shows which lines run on time and at what hours they fall behind.
          </p>
          <div className="mt-7 flex flex-wrap gap-3">
            <Button asChild>
              <Link to={`/${region.slug}/lines`}>Browse lines</Link>
            </Button>
            <Button asChild variant="outline">
              <Link to={`/${region.slug}/rankings`}>See rankings</Link>
            </Button>
          </div>
        </div>

        <section aria-labelledby="network-now" className="rounded-md border border-border bg-card p-5">
          <SectionTitle id="network-now">Network right now</SectionTitle>
          <div className="mt-3">
            {!connected ? (
              <RealtimeNotConnected operator={region.operator} />
            ) : live.isPending ? (
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
                  operator={region.operator}
                  timeZone={region.timezone}
                />
              </div>
            )}
          </div>
        </section>
      </section>

      {connected ? (
        <>
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
                    {region.operator} service may be paused overnight, or the background worker is not running.
                  </EmptyPanel>
                )
              ) : null}
            </div>
          </section>

          <section aria-labelledby="past-day" className="border-t border-border py-10">
            <SectionTitle id="past-day">Past 24 hours</SectionTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              On-time share by line over the last 24 complete hours. A line needs at least{' '}
              {OVERVIEW_MIN_ARRIVALS} observed arrivals to be ranked.
            </p>
            <div className="mt-4">
              {rankings.isPending ? (
                <LoadingPanel label="Loading rankings" />
              ) : rankings.isError ? (
                <ErrorPanel what="rankings" error={rankings.error} onRetry={() => void rankings.refetch()} />
              ) : ranked.length === 0 ? (
                <EmptyPanel
                  title={`No line has ${OVERVIEW_MIN_ARRIVALS} observed arrivals in the past 24 hours yet.`}
                >
                  Rankings appear once the background worker has been collecting data for a few hours.
                </EmptyPanel>
              ) : (
                <div className="grid gap-4 md:grid-cols-2">
                  <RankedList title="Most reliable" region={region} routes={mostReliable} lookup={lookup} />
                  {leastReliable.length > 0 ? (
                    <RankedList title="Least reliable" region={region} routes={leastReliable} lookup={lookup} />
                  ) : null}
                </div>
              )}
            </div>
            <p className="mt-5">
              <Link to={`/${region.slug}/rankings`} className="font-medium underline underline-offset-4">
                All {region.name} rankings and filters
              </Link>
            </p>
          </section>
        </>
      ) : null}
    </Container>
  )
}
