import { useSearchParams } from 'react-router-dom'

import {
  Container,
  EmptyPanel,
  ErrorPanel,
  JobMessage,
  LoadingPanel,
  PageHeader,
  SectionTitle,
} from '@/components/common'
import { RunTimeline } from '@/components/RunTimeline'
import { StatusNav } from '@/components/StatusNav'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { JobRunGroup, RunStatus } from '@/lib/api'
import { formatCount, formatDuration, formatPercent, localDateTime } from '@/lib/format'
import { JOB_DESCRIPTIONS, RUN_STATUS_STYLES, jobName } from '@/lib/jobs'
import { useJobRunHistory, useJobRuns, useJobSummary, useRegions } from '@/lib/queries'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { cn } from '@/lib/utils'

const PERIODS = ['24', '168', '720'] as const
const STATUSES = ['all', 'success', 'partial', 'failed', 'skipped', 'interrupted'] as const

const PERIOD_LABELS: Record<(typeof PERIODS)[number], string> = {
  '24': 'Past 24 hours',
  '168': 'Past 7 days',
  '720': 'Past 30 days (all that is kept)',
}

const PAGE_SIZE = 50

// Use a value from the address bar if it is one of the allowed options, otherwise the default, so a
// hand-edited or stale link still renders something sensible.
function pick<T extends string>(value: string | null, allowed: readonly T[], fallback: T): T {
  return value !== null && (allowed as readonly string[]).includes(value) ? (value as T) : fallback
}

// One job's row in the summary table: how many times it ran, how it ended, how long it took, and
// how much it wrote. Every figure comes from the API; a missing one reads "n/a" rather than zero.
function SummaryRow({ group }: { group: JobRunGroup }) {
  return (
    <TableRow>
      <TableCell className="min-w-56 whitespace-normal">
        <p className="font-medium">{jobName(group.job)}</p>
        <p className="text-xs text-muted-foreground">
          {JOB_DESCRIPTIONS[group.job]?.description ?? ''}
        </p>
      </TableCell>
      <TableCell className="text-right font-mono">{formatCount(group.run_count)}</TableCell>
      <TableCell className="text-right font-mono">{formatCount(group.success_count)}</TableCell>
      <TableCell className="text-right font-mono">{formatCount(group.partial_count)}</TableCell>
      <TableCell className="text-right font-mono">
        {formatCount(group.failed_count + group.interrupted_count)}
      </TableCell>
      <TableCell className="text-right font-mono">{formatCount(group.skipped_count)}</TableCell>
      <TableCell className="text-right font-mono">{formatPercent(group.success_rate)}</TableCell>
      <TableCell className="whitespace-nowrap">
        {group.timed_run_count > 0 ? (
          <>
            {formatDuration(group.p50_duration_seconds)}
            <span className="block text-xs text-muted-foreground">
              90th: {formatDuration(group.p90_duration_seconds)}
            </span>
          </>
        ) : (
          'n/a'
        )}
      </TableCell>
      <TableCell className="text-right font-mono">{formatCount(group.rows_written)}</TableCell>
      <TableCell className="max-w-72 whitespace-normal text-xs">
        <JobMessage error={group.last_error} />
      </TableCell>
    </TableRow>
  )
}

// The run history page: what every background job has actually been doing, grouped by agency and
// job, with an hour-by-hour timeline and the individual runs behind it. Filters are kept in the
// address bar so a particular view can be shared as a link.
export function RunHistoryPage() {
  useDocumentTitle('Run history')
  const [params, setParams] = useSearchParams()
  const hours = Number(pick(params.get('hours'), PERIODS, '24'))
  const job = params.get('job') ?? 'all'
  const agency = params.get('agency') ?? 'all'
  const status = pick(params.get('status'), STATUSES, 'all')
  const page = Math.max(0, Number(params.get('page') ?? '0') || 0)

  const filters = {
    hours,
    job: job === 'all' ? undefined : job,
    agency: agency === 'all' ? undefined : agency,
  }
  const summary = useJobSummary(filters)
  const timeline = useJobRunHistory(filters)
  const runs = useJobRuns({
    ...filters,
    status: status === 'all' ? undefined : (status as RunStatus),
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  })
  const regions = useRegions()
  const agencies = (regions.data ?? []).flatMap((region) => region.agencies)
  const agencyName = (slug: string | null) =>
    slug === null ? 'All cities' : (agencies.find((item) => item.slug === slug)?.name ?? slug)

  // Change one filter in the address bar, keep the others, and go back to the first page, since a
  // page number from the old filters would land the reader somewhere arbitrary.
  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params)
    next.set(key, value)
    next.delete('page')
    setParams(next, { replace: true })
  }

  // Move through the pages of the runs list, keeping every filter.
  function setPage(value: number) {
    const next = new URLSearchParams(params)
    next.set('page', String(value))
    setParams(next, { replace: true })
  }

  // The summary grouped into one section per agency, in the order the API returned them.
  const byAgency = new Map<string | null, JobRunGroup[]>()
  for (const group of summary.data?.jobs ?? []) {
    byAgency.set(group.agency, [...(byAgency.get(group.agency) ?? []), group])
  }

  const first = page * PAGE_SIZE + 1
  const last = page * PAGE_SIZE + (runs.data?.runs.length ?? 0)

  return (
    <Container>
      <PageHeader
        title="Run history"
        description="Every background job run Linecheck has recorded, how long it took, and what failed."
      />
      <StatusNav />

      <div className="mt-6 flex flex-wrap items-end gap-4">
        <div className="w-56">
          <Label htmlFor="history-period">Period</Label>
          <Select value={String(hours)} onValueChange={(value) => setFilter('hours', value)}>
            <SelectTrigger id="history-period" className="mt-1.5 w-full bg-card">
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
        <div className="w-52">
          <Label htmlFor="history-job">Job</Label>
          <Select value={job} onValueChange={(value) => setFilter('job', value)}>
            <SelectTrigger id="history-job" className="mt-1.5 w-full bg-card">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All jobs</SelectItem>
              {Object.keys(JOB_DESCRIPTIONS).map((value) => (
                <SelectItem key={value} value={value}>
                  {jobName(value)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="w-52">
          <Label htmlFor="history-agency">Agency</Label>
          <Select value={agency} onValueChange={(value) => setFilter('agency', value)}>
            <SelectTrigger id="history-agency" className="mt-1.5 w-full bg-card">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All agencies</SelectItem>
              {agencies.map((item) => (
                <SelectItem key={item.slug} value={item.slug}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <section aria-labelledby="run-summary" className="mt-10">
        <SectionTitle id="run-summary">How each job has been doing</SectionTitle>
        <p className="mb-3 mt-1 text-sm text-muted-foreground">
          Skipped runs never started, because the job was already running, so they are left out of the
          success rate.
        </p>
        {summary.isPending ? (
          <LoadingPanel rows={6} label="Loading job summary" />
        ) : summary.isError ? (
          <ErrorPanel
            what="the job summary"
            error={summary.error}
            onRetry={() => void summary.refetch()}
          />
        ) : summary.data.jobs.length === 0 ? (
          <EmptyPanel title="No job runs recorded in this period.">
            Choose a longer period, or check that the background worker is running.
          </EmptyPanel>
        ) : (
          [...byAgency.entries()].map(([slug, groups]) => (
            <section key={slug ?? 'all'} aria-label={agencyName(slug)} className="mb-8">
              <h3 className="font-display text-xl font-bold uppercase tracking-wide">
                {agencyName(slug)}
              </h3>
              <div className="mt-2 overflow-x-auto rounded-md border border-border bg-card">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Job</TableHead>
                      <TableHead className="text-right">Runs</TableHead>
                      <TableHead className="text-right">Succeeded</TableHead>
                      <TableHead className="text-right">Partial</TableHead>
                      <TableHead className="text-right">Did not finish</TableHead>
                      <TableHead className="text-right">Skipped</TableHead>
                      <TableHead className="text-right">Success rate</TableHead>
                      <TableHead>Median duration</TableHead>
                      <TableHead className="text-right">Rows written</TableHead>
                      <TableHead>Last failure</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {groups.map((group) => (
                      <SummaryRow key={`${group.job}:${group.agency ?? 'all'}`} group={group} />
                    ))}
                  </TableBody>
                </Table>
              </div>
            </section>
          ))
        )}
      </section>

      <section aria-labelledby="run-timeline" className="mt-10 border-t border-border pt-10">
        <SectionTitle id="run-timeline">Hour by hour</SectionTitle>
        <p className="mb-3 mt-1 text-sm text-muted-foreground">
          One cell per hour in your local time, coloured by what happened in it.
        </p>
        {timeline.isPending ? (
          <LoadingPanel rows={4} label="Loading the run timeline" />
        ) : timeline.isError ? (
          <ErrorPanel
            what="the run timeline"
            error={timeline.error}
            onRetry={() => void timeline.refetch()}
          />
        ) : (
          <RunTimeline hours={timeline.data.hours} />
        )}
      </section>

      <section aria-labelledby="recent-runs" className="mt-10 border-t border-border pt-10">
        <SectionTitle id="recent-runs">Individual runs</SectionTitle>
        <div className="mb-3 mt-1 flex flex-wrap items-end justify-between gap-4">
          <p className="text-sm text-muted-foreground">Newest first.</p>
          <div className="w-52">
            <Label htmlFor="history-status">Outcome</Label>
            <Select value={status} onValueChange={(value) => setFilter('status', value)}>
              <SelectTrigger id="history-status" className="mt-1.5 w-full bg-card">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All outcomes</SelectItem>
                {STATUSES.filter((value) => value !== 'all').map((value) => (
                  <SelectItem key={value} value={value}>
                    {RUN_STATUS_STYLES[value as RunStatus].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        {runs.isPending ? (
          <LoadingPanel rows={8} label="Loading runs" />
        ) : runs.isError ? (
          <ErrorPanel what="the list of runs" error={runs.error} onRetry={() => void runs.refetch()} />
        ) : runs.data.runs.length === 0 ? (
          <EmptyPanel title="No runs match these filters.">
            Try a longer period, another job, or a different outcome.
          </EmptyPanel>
        ) : (
          <>
            <div className="overflow-x-auto rounded-md border border-border bg-card">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Started</TableHead>
                    <TableHead>Job</TableHead>
                    <TableHead>Agency</TableHead>
                    <TableHead>Outcome</TableHead>
                    <TableHead>Duration</TableHead>
                    <TableHead className="text-right">Rows</TableHead>
                    <TableHead>Message</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {runs.data.runs.map((run) => {
                    const style = RUN_STATUS_STYLES[run.status]
                    return (
                      <TableRow key={run.id}>
                        <TableCell className="whitespace-nowrap">
                          {localDateTime(run.started_at)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">{jobName(run.job)}</TableCell>
                        <TableCell className="whitespace-nowrap">{agencyName(run.agency)}</TableCell>
                        <TableCell>
                          <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                            <span
                              className={cn('size-2.5 rounded-[2px]', style.className)}
                              aria-hidden="true"
                            />
                            {style.label}
                          </span>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          {run.duration_seconds === null
                            ? 'n/a'
                            : formatDuration(run.duration_seconds)}
                        </TableCell>
                        <TableCell className="text-right font-mono">
                          {run.rows === null ? 'n/a' : formatCount(run.rows)}
                        </TableCell>
                        <TableCell className="max-w-80 whitespace-normal text-xs">
                          <JobMessage error={run.error} />
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
              <p>
                Showing {formatCount(first)} to {formatCount(last)} of {formatCount(runs.data.total)}
              </p>
              <div className="flex gap-2">
                <Button variant="outline" disabled={page === 0} onClick={() => setPage(page - 1)}>
                  Newer
                </Button>
                <Button
                  variant="outline"
                  disabled={!runs.data.has_more}
                  onClick={() => setPage(page + 1)}
                >
                  Older
                </Button>
              </div>
            </div>
          </>
        )}
      </section>
    </Container>
  )
}
