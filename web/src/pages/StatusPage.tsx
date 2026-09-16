import {
  Container,
  ErrorPanel,
  JobMessage,
  LoadingPanel,
  PageHeader,
  SectionTitle,
} from '@/components/common'
import { StatusNav } from '@/components/StatusNav'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatAge, formatDuration, localDateTime, localTime } from '@/lib/format'
import { JOB_DESCRIPTIONS, STATE_STYLES } from '@/lib/jobs'
import { useHealth, useRegions } from '@/lib/queries'
import { useDocumentTitle } from '@/lib/useDocumentTitle'
import { cn } from '@/lib/utils'

// The status page: whether the API can reach its database and whether each background job is
// running on schedule for each agency, with the most recent error if a job is failing. Jobs that
// wait for an API key are listed but do not count as a problem. Times are in the reader's own time
// zone. Refreshes every 30 seconds.
export function StatusPage() {
  useDocumentTitle('Status')
  const health = useHealth()
  const regions = useRegions()
  const agencyNames = new Map(
    (regions.data ?? []).flatMap((region) => region.agencies.map((agency) => [agency.slug, agency.name])),
  )
  const waiting = health.data?.jobs.some((job) => job.state === 'not_configured') ?? false

  return (
    <Container>
      <PageHeader
        title="Service status"
        description="Whether Linecheck is collecting fresh transit data right now."
      />
      <StatusNav />
      <div className="mt-8">
        {health.isPending ? (
          <LoadingPanel rows={5} label="Loading service status" />
        ) : health.isError ? (
          <ErrorPanel what="service status" error={health.error} onRetry={() => void health.refetch()} />
        ) : (
          <>
            <div className="rounded-md border border-border bg-card p-5">
              <p className="flex items-center gap-3 font-display text-3xl font-bold uppercase tracking-wide">
                <span
                  className={cn(
                    'size-4 rounded-[3px]',
                    health.data.status === 'ok' ? 'bg-severity-on-time' : 'bg-severity-major',
                  )}
                  aria-hidden="true"
                />
                {health.data.status === 'ok' ? 'All systems running' : 'Something needs attention'}
              </p>
              <p className="mt-2 text-sm text-muted-foreground">
                Database {health.data.database === 'up' ? 'reachable' : 'unreachable'}. Checked at{' '}
                {localTime(health.data.checked_at)} your time.
              </p>
            </div>

            {health.data.jobs.length > 0 ? (
              <section aria-labelledby="jobs" className="mt-10">
                <SectionTitle id="jobs">Background jobs</SectionTitle>
                {waiting ? (
                  <p className="mt-1 text-sm text-muted-foreground">
                    Jobs marked Needs API key stay switched off until that agency&apos;s API key is configured
                    on the server. They do not count as a problem.
                  </p>
                ) : null}
                <div className="mt-3 overflow-x-auto rounded-md border border-border bg-card">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Job</TableHead>
                        <TableHead>Agency</TableHead>
                        <TableHead>State</TableHead>
                        <TableHead>Last success</TableHead>
                        <TableHead>Behind schedule after</TableHead>
                        <TableHead>Last error</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {health.data.jobs.map((job) => {
                        const about = JOB_DESCRIPTIONS[job.job] ?? { name: job.job, description: '' }
                        const style = STATE_STYLES[job.state]
                        const agency =
                          job.agency === null ? 'All cities' : (agencyNames.get(job.agency) ?? job.agency)
                        return (
                          <TableRow key={`${job.job}:${job.agency ?? 'all'}`}>
                            <TableCell className="min-w-56 whitespace-normal">
                              <p className="font-medium">{about.name}</p>
                              <p className="text-xs text-muted-foreground">{about.description}</p>
                            </TableCell>
                            <TableCell className="whitespace-nowrap">{agency}</TableCell>
                            <TableCell>
                              <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
                                <span className={cn('size-2.5 rounded-[2px]', style.className)} aria-hidden="true" />
                                {style.label}
                              </span>
                              {job.last_status === 'partial' ? (
                                <span className="block text-xs text-muted-foreground">
                                  Last run finished with something missing
                                </span>
                              ) : null}
                            </TableCell>
                            <TableCell className="whitespace-nowrap">
                              {job.last_success_at ? (
                                <>
                                  {formatAge(job.seconds_since_success)}
                                  <span className="block text-xs text-muted-foreground">
                                    {localDateTime(job.last_success_at)}
                                  </span>
                                </>
                              ) : (
                                'Never'
                              )}
                            </TableCell>
                            <TableCell className="whitespace-nowrap">{formatDuration(job.max_age_seconds)}</TableCell>
                            <TableCell className="max-w-80 whitespace-normal text-xs">
                              <JobMessage error={job.last_error} />
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </div>
              </section>
            ) : null}
          </>
        )}
      </div>
    </Container>
  )
}
