import { Link } from 'react-router-dom'

import {
  Container,
  EmptyPanel,
  ErrorPanel,
  Freshness,
  LoadingPanel,
  RealtimeNotConnected,
  SectionTitle,
  SeverityBar,
} from '@/components/common'
import { Button } from '@/components/ui/button'
import type { Region } from '@/lib/api'
import { formatCount } from '@/lib/format'
import { useRegionLive, useRegions } from '@/lib/queries'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// The operators of one city written as a sentence list, for example "LA Metro Bus, LA Metro Rail and
// LADOT Transit". A city with a single operator is just its name.
function agencyList(region: Region): string {
  const names = region.agencies.map((agency) => agency.name)
  if (names.length < 2) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

// One city on the home page: its name and agencies, how many vehicles are reporting right now and
// how late they are (or a notice when its live feeds are not connected), and links into the city.
function CityCard({ region }: { region: Region }) {
  const live = useRegionLive(region.slug, region.realtime_configured)
  const headingId = `city-${region.slug}`

  return (
    <section aria-labelledby={headingId} className="flex flex-col rounded-md border border-border bg-card p-5">
      <SectionTitle id={headingId}>{region.name}</SectionTitle>
      <p className="mt-1 text-sm text-muted-foreground">{agencyList(region)}</p>

      <div className="mt-4 flex-1">
        {!region.realtime_configured ? (
          <RealtimeNotConnected operator={region.operator} />
        ) : live.isPending ? (
          <LoadingPanel label={`Loading live ${region.name} data`} />
        ) : live.isError ? (
          <ErrorPanel what={`live ${region.name} data`} error={live.error} onRetry={() => void live.refetch()} />
        ) : (
          <div className="space-y-4">
            <p className="flex flex-wrap items-baseline gap-x-3">
              <span className="font-mono text-5xl font-medium">
                {formatCount(live.data.summary.vehicle_count)}
              </span>
              <span className="text-muted-foreground">
                vehicles reporting, {formatCount(live.data.summary.vehicles_with_delay)} with a delay estimate
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

      <div className="mt-5 flex flex-wrap gap-3">
        <Button asChild>
          <Link to={`/${region.slug}`}>Open {region.name}</Link>
        </Button>
        <Button asChild variant="outline">
          <Link to={`/${region.slug}/lines`}>{region.name} lines</Link>
        </Button>
      </div>
    </section>
  )
}

// The home page. It says what Linecheck does, then shows each city it covers with that city's live
// network state. Every number comes from the API.
export function HomePage() {
  useDocumentTitle(null)
  const regions = useRegions()

  return (
    <Container>
      <section className="border-b border-border py-10 lg:py-14">
        <h1 className="max-w-4xl font-display text-5xl font-bold uppercase leading-[0.95] tracking-wide sm:text-6xl">
          Live and historical reliability for Boston, Los Angeles and Orange County bus and rail lines
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-muted-foreground">
          Linecheck compares where buses and trains are against the published timetable every minute,
          then shows which lines run on time and at what hours they fall behind.
        </p>
      </section>

      <section aria-labelledby="cities" className="py-10">
        <h2 id="cities" className="sr-only">
          Cities
        </h2>
        {regions.isPending ? (
          <LoadingPanel rows={4} label="Loading cities" />
        ) : regions.isError ? (
          <ErrorPanel what="the list of cities" error={regions.error} onRetry={() => void regions.refetch()} />
        ) : regions.data.length === 0 ? (
          <EmptyPanel title="No cities are switched on.">
            Set <code className="font-mono">ENABLED_REGIONS</code> in the server configuration.
          </EmptyPanel>
        ) : (
          <div className="grid gap-4 md:grid-cols-2">
            {regions.data.map((region) => (
              <CityCard key={region.slug} region={region} />
            ))}
          </div>
        )}
      </section>
    </Container>
  )
}
