import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import {
  Container,
  EmptyPanel,
  ErrorPanel,
  LoadingPanel,
  PageHeader,
  RouteBadge,
  SectionTitle,
} from '@/components/common'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { Route } from '@/lib/api'
import { MODE_ORDER, formatCount, modeName, routeName } from '@/lib/format'
import { useRoutes } from '@/lib/queries'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// Whether a route matches what the reader typed: its displayed name, full name, number, or id.
function matchesSearch(route: Route, term: string): boolean {
  if (!term) return true
  const haystack = [routeName(route), route.route_long_name, route.route_short_name, route.route_id]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  return haystack.includes(term)
}

// Split routes into one group per mode, in MODE_ORDER, keeping the MBTA's order inside each group.
function groupByMode(routes: Route[]): { routeType: number; routes: Route[] }[] {
  const order = [...MODE_ORDER, ...new Set(routes.map((route) => route.route_type))].filter(
    (value, index, all) => all.indexOf(value) === index,
  )
  return order
    .map((routeType) => ({
      routeType,
      routes: routes.filter((route) => route.route_type === routeType),
    }))
    .filter((group) => group.routes.length > 0)
}

// The lines page: every route in the MBTA timetable grouped by mode, with a search box that filters
// by name or number. Each route links to its live page.
export function LinesPage() {
  useDocumentTitle('Lines')
  const routes = useRoutes()
  const [search, setSearch] = useState('')
  const term = search.trim().toLowerCase()
  const groups = useMemo(
    () => groupByMode((routes.data ?? []).filter((route) => matchesSearch(route, term))),
    [routes.data, term],
  )

  return (
    <Container>
      <PageHeader
        title="Lines"
        description="Every route in the MBTA timetable. Pick one to see its vehicles right now and its on-time record by hour."
      />
      <div className="mt-6 max-w-sm">
        <Label htmlFor="line-search">Find a line</Label>
        <Input
          id="line-search"
          type="search"
          className="mt-1.5 bg-card"
          placeholder="Red Line, 39, Fitchburg"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      <div className="mt-8">
        {routes.isPending ? (
          <LoadingPanel rows={6} label="Loading lines" />
        ) : routes.isError ? (
          <ErrorPanel what="the list of lines" error={routes.error} onRetry={() => void routes.refetch()} />
        ) : routes.data.length === 0 ? (
          <EmptyPanel title="The MBTA timetable has not been loaded yet.">
            Load it with <code className="font-mono">uv run python -m app.gtfs.static_loader</code> or start
            the background worker.
          </EmptyPanel>
        ) : groups.length === 0 ? (
          <EmptyPanel title={`No line matches "${search.trim()}".`}>
            Try a route number such as 39, or part of a line name such as Orange.
          </EmptyPanel>
        ) : (
          groups.map((group) => (
            <section
              key={group.routeType}
              aria-labelledby={`mode-${group.routeType}`}
              className="mb-10"
            >
              <SectionTitle id={`mode-${group.routeType}`}>
                {modeName(group.routeType)}{' '}
                <span className="font-mono text-base font-normal text-muted-foreground">
                  ({formatCount(group.routes.length)})
                </span>
              </SectionTitle>
              <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {group.routes.map((route) => (
                  <li key={route.route_id}>
                    <Link
                      to={`/lines/${encodeURIComponent(route.route_id)}`}
                      className="flex items-center gap-3 rounded-md border border-border bg-card px-3 py-2.5 hover:border-foreground"
                    >
                      <RouteBadge route={route} routeId={route.route_id} />
                      <span className="min-w-0">
                        <span className="block truncate font-medium">{routeName(route)}</span>
                        {route.route_type === 3 && route.route_long_name ? (
                          <span className="block truncate text-xs text-muted-foreground">
                            {route.route_long_name}
                          </span>
                        ) : null}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
    </Container>
  )
}
