import { Link } from 'react-router-dom'

import { EmptyPanel, ErrorPanel, LoadingPanel, RouteBadge } from '@/components/common'
import type { Alerts, Region, Route, ServiceAlert } from '@/lib/api'
import { alertCause, alertEffect, localDateTime } from '@/lib/format'
import { routeKey } from '@/lib/queries'
import { linePath } from '@/lib/regions'
import { cn } from '@/lib/utils'

// What a query for alerts looks like to this panel: only the parts it reads, so it works with any
// of the alert hooks without depending on TanStack Query's full result type.
type AlertsQuery = {
  isPending: boolean
  isError: boolean
  error: Error | null
  data?: Alerts
  refetch: () => void
}

// The tag shown on an alert: the agency's stated cause ("Crash", "Police activity") when there is
// one, otherwise what it does to service ("Detour"). Severe alerts are marked in the severe color,
// so a crash does not look like planned weekend work.
function AlertTag({ alert }: { alert: ServiceAlert }) {
  const label = alertCause(alert.cause) ?? alertEffect(alert.effect)
  if (!label) return null
  const severe = alert.severity_level === 'SEVERE' || alert.cause === 'ACCIDENT'
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center rounded-sm px-1.5 py-0.5 text-xs font-medium',
        severe ? 'bg-severity-severe text-background' : 'bg-muted text-foreground',
      )}
    >
      {label}
    </span>
  )
}

// One alert: its tag, the agency's own headline and description, which lines it names, and when it
// started or ends. Every word of the text comes from the agency; nothing here is written by
// Linecheck or inferred from the delay figures.
function AlertItem({
  alert,
  region,
  lookup,
  showRoutes,
}: {
  alert: ServiceAlert
  region: Region
  lookup: Map<string, Route>
  showRoutes: boolean
}) {
  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start gap-2">
        <AlertTag alert={alert} />
        <p className="min-w-0 flex-1 font-medium">{alert.header ?? 'Service alert'}</p>
      </div>
      {alert.description && alert.description !== alert.header ? (
        <p className="mt-1.5 whitespace-pre-line text-sm text-muted-foreground">
          {alert.description}
        </p>
      ) : null}
      {showRoutes && alert.routes.length > 0 ? (
        <ul className="mt-2 flex flex-wrap gap-1.5">
          {alert.routes.slice(0, 12).map((routeId) => {
            const route = lookup.get(routeKey(alert.agency, routeId))
            return (
              <li key={routeId}>
                <Link to={linePath(region.slug, alert.agency, routeId)} className="rounded-sm">
                  <RouteBadge route={route} routeId={routeId} />
                </Link>
              </li>
            )
          })}
          {alert.routes.length > 12 ? (
            <li className="self-center text-xs text-muted-foreground">
              and {alert.routes.length - 12} more
            </li>
          ) : null}
        </ul>
      ) : null}
      <p className="mt-2 text-xs text-muted-foreground">
        {alert.starts_at ? `Since ${localDateTime(alert.starts_at, region.timezone)}` : 'In force'}
        {alert.ends_at ? ` until ${localDateTime(alert.ends_at, region.timezone)}` : null}
        {alert.url ? (
          <>
            {' '}
            <a
              className="underline underline-offset-4"
              href={alert.url}
              target="_blank"
              rel="noreferrer"
            >
              Agency notice
            </a>
          </>
        ) : null}
      </p>
    </li>
  )
}

// The service news panel: what the agencies themselves say is happening right now, newest first.
// It handles loading, failure (with a working retry) and the good case where nothing is wrong.
// `limit` caps how many are listed, for the city page where the panel sits beside other content.
export function AlertsPanel({
  query,
  region,
  lookup,
  limit,
  showRoutes = true,
  emptyTitle = 'No service alerts right now.',
}: {
  query: AlertsQuery
  region: Region
  lookup: Map<string, Route>
  limit?: number
  showRoutes?: boolean
  emptyTitle?: string
}) {
  if (query.isPending) return <LoadingPanel rows={2} label="Loading service alerts" />
  if (query.isError) {
    return (
      <ErrorPanel
        what="service alerts"
        error={query.error}
        onRetry={() => {
          query.refetch()
        }}
      />
    )
  }
  const alerts = query.data?.alerts ?? []
  if (alerts.length === 0) {
    return (
      <EmptyPanel title={emptyTitle}>
        Alerts appear here when an agency publishes one, such as a crash, police activity, a detour,
        or planned work.
      </EmptyPanel>
    )
  }
  const shown = limit ? alerts.slice(0, limit) : alerts
  return (
    <div>
      <ul className="divide-y divide-border">
        {shown.map((alert) => (
          <AlertItem
            key={`${alert.agency}:${alert.alert_id}`}
            alert={alert}
            region={region}
            lookup={lookup}
            showRoutes={showRoutes}
          />
        ))}
      </ul>
      {limit && alerts.length > limit ? (
        <p className="mt-3 text-sm text-muted-foreground">
          {alerts.length - limit} more alert{alerts.length - limit === 1 ? '' : 's'} in force.
        </p>
      ) : null}
    </div>
  )
}
