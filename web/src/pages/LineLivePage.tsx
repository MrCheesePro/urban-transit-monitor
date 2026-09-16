import { useState } from 'react'
import { useParams } from 'react-router-dom'

import {
  Container,
  EmptyPanel,
  ErrorPanel,
  Freshness,
  LoadingPanel,
  RealtimeNotConnected,
  SectionTitle,
  SeverityBadge,
  StatTile,
} from '@/components/common'
import { AlertsPanel } from '@/components/AlertsPanel'
import { LineHeader, LineNotFound } from '@/components/LineHeader'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { VehicleMap } from '@/components/VehicleMap'
import type { LiveVehicle } from '@/lib/api'
import {
  describeDelay,
  formatAge,
  formatCount,
  routeName,
  secondsSince,
  signedDelay,
} from '@/lib/format'
import { useLiveRoute, useRegionRoutes, useRouteAlerts, useRouteLookup } from '@/lib/queries'
import { regionCenter, useRegion } from '@/lib/regions'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

type DirectionChoice = 'both' | '0' | '1'

// Where a vehicle is, in words, using the stop's name from the timetable when there is one, for
// example "Stopped at Harvard" or "Heading to Union Station".
function positionText(vehicle: LiveVehicle): string {
  const stop = vehicle.stop_name ?? (vehicle.stop_id ? `stop ${vehicle.stop_id}` : null)
  if (stop === null) return 'Location on map only'
  if (vehicle.current_status === 'STOPPED_AT') return `Stopped at ${stop}`
  if (vehicle.current_status === 'INCOMING_AT') return `Arriving at ${stop}`
  return `Heading to ${stop}`
}

// Latest vehicles first by how late they are, with vehicles that have no estimate at the end.
function byDelay(a: LiveVehicle, b: LiveVehicle): number {
  if (a.delay_seconds === null) return b.delay_seconds === null ? 0 : 1
  if (b.delay_seconds === null) return -1
  return b.delay_seconds - a.delay_seconds
}

// A line's live page: every vehicle heard from in the last few minutes on a map and in a table,
// each with its estimated delay, plus the line's overall status. Refreshes every 30 seconds. For a
// city whose live feeds are not connected it says so instead.
export function LineLivePage() {
  const region = useRegion()
  const { agency = '', routeId = '' } = useParams()
  const routes = useRegionRoutes(region.slug)
  const route = routes.data?.find(
    (candidate) => candidate.agency === agency && candidate.route_id === routeId,
  )
  const [direction, setDirection] = useState<DirectionChoice>('both')
  const live = useLiveRoute(agency, routeId, direction === 'both' ? undefined : Number(direction))
  const alerts = useRouteAlerts(agency, routeId)
  const lookup = useRouteLookup(region.slug)
  useDocumentTitle(route ? `${routeName(route)} live` : 'Line')

  if (routes.data && !route) return <LineNotFound region={region} routeId={routeId} />
  const vehicles = [...(live.data?.vehicles ?? [])].sort(byDelay)
  const connected = live.data?.realtime_configured ?? true

  return (
    <Container>
      <LineHeader region={region} agency={agency} route={route} routeId={routeId} />

      {connected ? (
        <div className="mt-6 flex flex-wrap items-end justify-between gap-4">
          <div className="w-52">
            <Label htmlFor="direction">Direction</Label>
            <Select value={direction} onValueChange={(value) => setDirection(value as DirectionChoice)}>
              <SelectTrigger id="direction" className="mt-1.5 w-full bg-card">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="both">Both directions</SelectItem>
                <SelectItem value="0">Direction 0</SelectItem>
                <SelectItem value="1">Direction 1</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {live.data ? (
            <Freshness
              asOf={live.data.as_of}
              ageSeconds={live.data.data_age_seconds}
              stale={live.data.stale}
              operator={region.operator}
              timeZone={region.timezone}
            />
          ) : null}
        </div>
      ) : null}

      <section aria-labelledby="line-alerts" className="mt-8">
        <SectionTitle id="line-alerts">Service news</SectionTitle>
        <p className="mb-3 mt-1 text-sm text-muted-foreground">
          What the agency says about this line right now, in its own words.
        </p>
        <AlertsPanel
          query={alerts}
          region={region}
          lookup={lookup}
          showRoutes={false}
          emptyTitle="No service alerts for this line right now."
        />
      </section>

      <div className="mt-6">
        {live.isPending ? (
          <LoadingPanel rows={4} label="Loading live vehicles" />
        ) : live.isError ? (
          <ErrorPanel what="live vehicles" error={live.error} onRetry={() => void live.refetch()} />
        ) : !live.data.realtime_configured ? (
          <RealtimeNotConnected operator={region.operator} />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <StatTile label="Vehicles reporting" value={formatCount(live.data.summary.vehicle_count)} />
              <StatTile
                label="Median delay"
                value={describeDelay(live.data.summary.median_delay_seconds)}
                detail={`From ${formatCount(live.data.summary.vehicles_with_delay)} vehicles with an estimate`}
              />
              <StatTile label="Most delayed vehicle" value={describeDelay(live.data.summary.max_delay_seconds)} />
              <StatTile
                label="Line status"
                value={<SeverityBadge severity={live.data.summary.severity} className="font-sans" />}
              />
            </div>

            {vehicles.length === 0 ? (
              <div className="mt-8">
                <EmptyPanel title="No vehicles on this line in the last 5 minutes.">
                  Service may not be running right now. This page checks again every 30 seconds.
                </EmptyPanel>
              </div>
            ) : (
              <>
                <section aria-labelledby="vehicle-map" className="mt-10">
                  <SectionTitle id="vehicle-map">Map</SectionTitle>
                  <p className="mb-3 mt-1 text-sm text-muted-foreground">
                    Each dot is a vehicle, colored by how late it is.
                  </p>
                  <VehicleMap
                    vehicles={vehicles}
                    fitKey={`${agency}-${routeId}-${direction}`}
                    center={regionCenter(region.slug)}
                  />
                </section>

                <section aria-labelledby="vehicle-table" className="mt-10">
                  <SectionTitle id="vehicle-table">Vehicles</SectionTitle>
                  <p className="mb-3 mt-1 text-sm text-muted-foreground">
                    Most delayed first. Delay compares the next predicted arrival with the timetable.
                  </p>
                  <div className="overflow-x-auto rounded-md border border-border bg-card">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Vehicle</TableHead>
                          <TableHead>Direction</TableHead>
                          <TableHead>Where</TableHead>
                          <TableHead className="text-right">Delay</TableHead>
                          <TableHead>Status</TableHead>
                          <TableHead>Last report</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {vehicles.map((vehicle) => (
                          <TableRow key={vehicle.vehicle_id}>
                            <TableCell className="font-mono">{vehicle.label ?? vehicle.vehicle_id}</TableCell>
                            <TableCell>
                              {vehicle.direction_id === null ? 'Unknown' : `Direction ${vehicle.direction_id}`}
                            </TableCell>
                            <TableCell>{positionText(vehicle)}</TableCell>
                            <TableCell className="text-right font-mono">
                              {signedDelay(vehicle.delay_seconds)}
                            </TableCell>
                            <TableCell>
                              <SeverityBadge severity={vehicle.severity} />
                            </TableCell>
                            <TableCell className="text-muted-foreground">
                              {formatAge(secondsSince(vehicle.feed_timestamp))}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </section>
              </>
            )}
          </>
        )}
      </div>
    </Container>
  )
}
