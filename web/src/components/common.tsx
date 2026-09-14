import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import type { Route, Severity } from '@/lib/api'
import { ApiError } from '@/lib/api'
import {
  SEVERITY_BG,
  SEVERITY_LABELS,
  SEVERITY_ORDER,
  badgeLabel,
  bostonTime,
  formatAge,
  formatCount,
  hexColor,
} from '@/lib/format'
import { cn } from '@/lib/utils'

// Page width and side padding used by every page.
export function Container({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('mx-auto w-full max-w-6xl px-4 sm:px-6', className)}>{children}</div>
}

// The title block at the top of a page: an optional eyebrow naming the section the page belongs
// to, the heading, a one-sentence description, and optional extra content such as badges.
export function PageHeader({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow?: ReactNode
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="border-b border-border pb-6 pt-10">
      {eyebrow ? (
        <p className="mb-2 text-sm font-medium uppercase tracking-wider text-muted-foreground">
          {eyebrow}
        </p>
      ) : null}
      <h1 className="font-display text-4xl font-bold uppercase leading-none tracking-wide sm:text-5xl">
        {title}
      </h1>
      {description ? (
        <p className="mt-3 max-w-2xl text-base text-muted-foreground">{description}</p>
      ) : null}
      {children}
    </div>
  )
}

// A small tag in the route's official MBTA color with its short label (bus number, line name).
// Falls back to neutral colors when the timetable has no color for the route.
export function RouteBadge({ route, routeId }: { route?: Route; routeId: string }) {
  const background = hexColor(route?.route_color) ?? '#DDE3E0'
  const color = hexColor(route?.route_text_color) ?? '#15181C'
  return (
    <span
      className="inline-flex min-w-10 shrink-0 items-center justify-center rounded-sm px-1.5 py-0.5 font-mono text-xs font-medium"
      style={{ backgroundColor: background, color }}
    >
      {badgeLabel(route, routeId)}
    </span>
  )
}

// A severity shown as a small colored square followed by its name, so color is never the only way
// the information is conveyed.
export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 whitespace-nowrap', className)}>
      <span className={cn('size-2.5 rounded-[2px]', SEVERITY_BG[severity])} aria-hidden="true" />
      {SEVERITY_LABELS[severity]}
    </span>
  )
}

// A single bar split into solid segments, one per severity, sized by the number of vehicles in
// each, with a legend giving the exact counts. The legend is what screen readers read.
export function SeverityBar({ counts }: { counts: Record<Severity, number> }) {
  const total = SEVERITY_ORDER.reduce((sum, severity) => sum + (counts[severity] ?? 0), 0)
  return (
    <div>
      <div className="flex h-4 w-full overflow-hidden rounded-sm bg-muted" aria-hidden="true">
        {total > 0
          ? SEVERITY_ORDER.map((severity) =>
              counts[severity] ? (
                <div
                  key={severity}
                  className={SEVERITY_BG[severity]}
                  style={{ width: `${(counts[severity] / total) * 100}%` }}
                />
              ) : null,
            )
          : null}
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-3">
        {SEVERITY_ORDER.map((severity) => (
          <li key={severity} className="flex items-center justify-between gap-2">
            <SeverityBadge severity={severity} />
            <span className="font-mono">{formatCount(counts[severity] ?? 0)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// One labelled figure, such as "Median delay: 1 min 10 s late", with an optional detail line.
export function StatTile({
  label,
  value,
  detail,
}: {
  label: string
  value: ReactNode
  detail?: ReactNode
}) {
  return (
    <div className="rounded-md border border-border bg-card p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-1 font-mono text-xl font-medium">{value}</p>
      {detail ? <p className="mt-1 text-xs text-muted-foreground">{detail}</p> : null}
    </div>
  )
}

// Says when the MBTA published the live data on screen, and warns plainly when it is missing or
// too old to rely on.
export function Freshness({
  asOf,
  ageSeconds,
  stale,
}: {
  asOf: string | null
  ageSeconds: number | null
  stale: boolean
}) {
  if (!asOf) {
    return (
      <p className="text-sm text-severity-severe">
        No live data has been received yet. The background worker may not be running.
      </p>
    )
  }
  if (stale) {
    return (
      <p className="text-sm text-severity-severe">
        The latest MBTA data is from {bostonTime(asOf)} ({formatAge(ageSeconds)}). Live figures may be
        out of date.
      </p>
    )
  }
  return (
    <p className="text-sm text-muted-foreground">
      MBTA data from {bostonTime(asOf)} ({formatAge(ageSeconds)}). Updates every 30 seconds.
    </p>
  )
}

// Placeholder blocks shown while data is loading, roughly the shape of the content to come.
export function LoadingPanel({ rows = 3, label }: { rows?: number; label: string }) {
  return (
    <div role="status" aria-label={label} className="space-y-3">
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-10 w-full" />
      ))}
    </div>
  )
}

// Explains that a request failed, what the API said, and offers a retry. When the API is
// unreachable or broken it also says how to start it.
export function ErrorPanel({
  what,
  error,
  onRetry,
}: {
  what: string
  error: unknown
  onRetry: () => void
}) {
  const status = error instanceof ApiError ? error.status : 0
  const message = error instanceof Error ? error.message : 'Unknown error.'
  return (
    <div role="alert" className="rounded-md border border-severity-severe bg-card p-4">
      <p className="font-medium">Could not load {what}.</p>
      <p className="mt-1 text-sm text-muted-foreground">{message}</p>
      {status === 0 || status >= 500 ? (
        <p className="mt-1 text-sm text-muted-foreground">
          Check that the API is running, for example with <code className="font-mono">docker compose up</code>.
        </p>
      ) : null}
      <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
        Try again
      </Button>
    </div>
  )
}

// A clear message for when a request worked but there is nothing to show yet.
export function EmptyPanel({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-border bg-card p-6">
      <p className="font-medium">{title}</p>
      {children ? <div className="mt-1 text-sm text-muted-foreground">{children}</div> : null}
    </div>
  )
}

// A section heading inside a page, in the display face.
export function SectionTitle({ children, id }: { children: ReactNode; id?: string }) {
  return (
    <h2 id={id} className="font-display text-2xl font-bold uppercase tracking-wide">
      {children}
    </h2>
  )
}
