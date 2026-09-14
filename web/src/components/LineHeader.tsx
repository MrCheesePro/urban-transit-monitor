import { Link, NavLink } from 'react-router-dom'

import { Container, PageHeader, RouteBadge } from '@/components/common'
import type { Route } from '@/lib/api'
import { modeName, routeName } from '@/lib/format'
import { cn } from '@/lib/utils'

// The heading shared by a line's two pages: its badge, name, and mode, plus links to switch between
// the Live view and the History view of the same line.
export function LineHeader({ route, routeId }: { route?: Route; routeId: string }) {
  const base = `/lines/${encodeURIComponent(routeId)}`
  const tabs = [
    { to: base, label: 'Live', end: true },
    { to: `${base}/history`, label: 'History', end: false },
  ]
  const subtitle = route?.route_type === 3 ? route.route_long_name : null

  return (
    <PageHeader
      eyebrow={
        <Link to="/lines" className="hover:underline hover:underline-offset-4">
          {modeName(route?.route_type)}
        </Link>
      }
      title={
        <span className="inline-flex flex-wrap items-center gap-3">
          <RouteBadge route={route} routeId={routeId} />
          {routeName(route, routeId)}
        </span>
      }
      description={subtitle ?? undefined}
    >
      <nav aria-label="Line views" className="mt-6">
        <ul className="flex gap-1">
          {tabs.map((tab) => (
            <li key={tab.label}>
              <NavLink
                to={tab.to}
                end={tab.end}
                className={({ isActive }) =>
                  cn(
                    'block rounded-sm border-b-[3px] px-3 py-2 text-sm font-medium',
                    isActive
                      ? 'border-foreground text-foreground'
                      : 'border-transparent text-muted-foreground hover:text-foreground',
                  )
                }
              >
                {tab.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </PageHeader>
  )
}

// Shown instead of a line page when the address names a route that is not in the timetable.
export function LineNotFound({ routeId }: { routeId: string }) {
  return (
    <Container>
      <PageHeader
        title="Line not found"
        description={`There is no route with the id "${routeId}" in the MBTA timetable.`}
      />
      <p className="mt-6">
        <Link to="/lines" className="underline underline-offset-4">
          Browse all lines
        </Link>
      </p>
    </Container>
  )
}
