import type { JobState, RunStatus } from '@/lib/api'

// What each background job does, in words a visitor understands. Every job except data cleanup runs
// once per agency. Shared by the status page and the run history page.
export const JOB_DESCRIPTIONS: Record<string, { name: string; description: string }> = {
  poll_realtime: {
    name: 'Live vehicle updates',
    description: 'Downloads vehicle positions and predictions every minute.',
  },
  poll_alerts: {
    name: 'Service alerts',
    description: "Downloads the agency's own service alerts every 5 minutes.",
  },
  derive_stop_events: {
    name: 'Stop arrival estimates',
    description: 'Works out when vehicles reached each stop, every 5 minutes.',
  },
  aggregate_hourly: {
    name: 'Hourly statistics',
    description: 'Updates on-time and spacing figures at 15 minutes past each hour.',
  },
  load_static_gtfs: {
    name: 'Timetable download',
    description: 'Checks for a new timetable once a day.',
  },
  retention: {
    name: 'Data cleanup',
    description: 'Removes old records for every city once a day so storage stays bounded.',
  },
}

// The name a job is known by on screen, falling back to its internal name.
export function jobName(job: string): string {
  return JOB_DESCRIPTIONS[job]?.name ?? job
}

// How each health state is labelled and coloured on the status page.
export const STATE_STYLES: Record<JobState, { label: string; className: string }> = {
  ok: { label: 'Running', className: 'bg-severity-on-time' },
  failing: { label: 'Failing', className: 'bg-severity-severe' },
  stale: { label: 'Behind schedule', className: 'bg-severity-major' },
  never_run: { label: 'Not run yet', className: 'bg-severity-unknown' },
  not_configured: { label: 'Needs API key', className: 'bg-muted-foreground' },
}

// How each recorded outcome of a single run is labelled and coloured. "Partial" means the job did
// its work but something optional was missing, such as a poll that stored vehicles while the
// agency published no arrival predictions. "Skipped" means it never ran because another worker held
// the lock, which is why it is coloured as neither good nor bad.
export const RUN_STATUS_STYLES: Record<RunStatus, { label: string; className: string }> = {
  success: { label: 'Succeeded', className: 'bg-severity-on-time' },
  partial: { label: 'Partial', className: 'bg-severity-minor' },
  failed: { label: 'Failed', className: 'bg-severity-severe' },
  skipped: { label: 'Skipped', className: 'bg-severity-unknown' },
  interrupted: { label: 'Interrupted', className: 'bg-severity-major' },
  running: { label: 'Running', className: 'bg-muted-foreground' },
}
