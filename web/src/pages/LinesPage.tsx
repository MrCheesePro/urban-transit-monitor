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
import type { Region, Route } from '@/lib/api'
import { MODE_ORDER, formatCount, modeName, routeName } from '@/lib/format'
import { routeKey, useRegionRoutes } from '@/lib/queries'
import { linePath, regionSearchExample, useRegion } from '@/lib/regions'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// The value of the operator filter when no single operator is picked.
const ALL_OPERATORS = 'all'

// One list of routes under its own heading, for example "Torrance Transit" or "Bus".
type Group = { key: string; title: string; routes: Route[] }

// Whether a route matches what the reader typed: its displayed name, full name, number, or id.
function matchesSearch(route: Route, term: string): boolean {
  if (!term) return true
  const haystack = [routeName(route), route.route_long_name, route.route_short_name, route.route_id]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
  return haystack.includes(term)
}

// Split routes into one group per mode, in MODE_ORDER, keeping the API's order inside each group.
// Used when the reader is looking at a single operator, where the operator name adds nothing.
function groupByMode(routes: Route[]): Group[] {
  const order = [...MODE_ORDER, ...new Set(routes.map((route) => route.route_type))].filter(
    (value, index, all) => all.indexOf(value) === index,
  )
  return order
    .map((routeType) => ({
      key: `mode-${routeType}`,
      title: modeName(routeType),
      routes: routes.filter((route) => route.route_type === routeType),
    }))
    .filter((group) => group.routes.length > 0)
}

// Split routes into one group per operator, in the order the region lists them. Used when a region
// has several operators and all of them are shown, so that two lines numbered the same by different
// operators (Long Beach and Torrance both run a route 1) are told apart by the heading above them.
function groupByOperator(routes: Route[], region: Region): Group[] {
  return region.agencies
    .map((agency) => ({
      key: `agency-${agency.slug}`,
      title: agency.name,
      routes: routes.filter((route) => route.agency === agency.slug),
    }))
    .filter((group) => group.routes.length > 0)
}

// How many routes each operator has, so the filter can show a count next to every name.
function countByAgency(routes: Route[]): Map<string, number> {
  const counts = new Map<string, number>()
  for (const route of routes) {
    counts.set(route.agency, (counts.get(route.agency) ?? 0) + 1)
  }
  return counts
}

// The buttons that choose which operator to show. Only rendered for a region with more than one
// operator: "All operators" keeps them together under a heading each, and picking one narrows the
// page to that operator's lines.
function OperatorFilter({
  region,
  counts,
  total,
  value,
  onChange,
}: {
  region: Region
  counts: Map<string, number>
  total: number
  value: string
  onChange: (value: string) => void
}) {
  const options = [
    { slug: ALL_OPERATORS, name: 'All operators', count: total },
    ...region.agencies.map((agency) => ({
      slug: agency.slug,
      name: agency.name,
      count: counts.get(agency.slug) ?? 0,
    })),
  ]
  return (
    <div className="mt-6">
      <p className="text-sm font-medium" id="operator-filter-label">
        Operator
      </p>
      <ul className="mt-1.5 flex flex-wrap gap-2" aria-labelledby="operator-filter-label">
        {options.map((option) => {
          const active = option.slug === value
          return (
            <li key={option.slug}>
              <button
                type="button"
                aria-pressed={active}
                onClick={() => onChange(option.slug)}
                className={
                  active
                    ? 'rounded-sm border border-foreground bg-foreground px-3 py-1.5 text-sm font-medium text-background'
                    : 'rounded-sm border border-border bg-card px-3 py-1.5 text-sm font-medium text-muted-foreground hover:text-foreground'
                }
              >
                {option.name}{' '}
                <span className="font-mono text-xs">({formatCount(option.count)})</span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// A region's lines page: every route in its timetables, grouped by operator when the region has
// several and by mode when it has one, with a search box and (for a multi-operator region) buttons
// to show one operator at a time. Each route links to its live page.
export function LinesPage() {
  const region = useRegion()
  useDocumentTitle(`${region.name} lines`)
  const routes = useRegionRoutes(region.slug)
  const [search, setSearch] = useState('')
  const [operator, setOperator] = useState<string>(ALL_OPERATORS)
  const term = search.trim().toLowerCase()
  const manyOperators = region.agencies.length > 1
  const all = useMemo(() => routes.data ?? [], [routes.data])
  const counts = useMemo(() => countByAgency(all), [all])

  // The routes on screen and how they are divided: by operator while all operators are shown,
  // otherwise by mode, since the operator is then already known from the button that is pressed.
  const groups = useMemo(() => {
    const shown = all.filter(
      (route) =>
        matchesSearch(route, term) && (operator === ALL_OPERATORS || route.agency === operator),
    )
    return manyOperators && operator === ALL_OPERATORS
      ? groupByOperator(shown, region)
      : groupByMode(shown)
  }, [all, term, operator, manyOperators, region])

  const description = manyOperators
    ? `Every route in the timetables of ${region.name}. Pick one to see its vehicles right now and its on-time record by hour.`
    : `Every route in the ${region.operator} timetable. Pick one to see its vehicles right now and its on-time record by hour.`

  return (
    <Container>
      <PageHeader eyebrow={region.name} title="Lines" description={description} />

      {manyOperators ? (
        <OperatorFilter
          region={region}
          counts={counts}
          total={all.length}
          value={operator}
          onChange={setOperator}
        />
      ) : null}

      <div className="mt-6 max-w-sm">
        <Label htmlFor="line-search">Find a line</Label>
        <Input
          id="line-search"
          type="search"
          className="mt-1.5 bg-card"
          placeholder={regionSearchExample(region.slug)}
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
          <EmptyPanel title={`The ${region.operator} timetable has not been loaded yet.`}>
            Load it with <code className="font-mono">uv run python -m app.gtfs.static_loader</code> or start
            the background worker.
          </EmptyPanel>
        ) : groups.length === 0 ? (
          <EmptyPanel title={search.trim() ? `No line matches "${search.trim()}".` : 'No lines to show.'}>
            Try a route number or part of a line name, for example {regionSearchExample(region.slug)}.
          </EmptyPanel>
        ) : (
          groups.map((group) => (
            <section key={group.key} aria-labelledby={group.key} className="mb-10">
              <SectionTitle id={group.key}>
                {group.title}{' '}
                <span className="font-mono text-base font-normal text-muted-foreground">
                  ({formatCount(group.routes.length)})
                </span>
              </SectionTitle>
              <ul className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {group.routes.map((route) => (
                  <li key={routeKey(route.agency, route.route_id)}>
                    <Link
                      to={linePath(region.slug, route.agency, route.route_id)}
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
