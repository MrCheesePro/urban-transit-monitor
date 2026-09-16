import type { RunHour } from '@/lib/api'
import { formatCount } from '@/lib/format'

// What one hour of the run timeline shows: its colour, a short number that fits in the cell, and a
// full sentence for screen readers and hover text. An hour with no runs recorded is its own reading
// with its own colour and wording, never an empty cell, so nothing about it has to be inferred.
// Full class names are written out so Tailwind includes them in the build.
export function hourReading(
  hour: RunHour,
  when: string,
): { className: string; short: string; description: string } {
  const { run_count, failed_count, interrupted_count, partial_count, skipped_count } = hour
  const broken = failed_count + interrupted_count

  if (run_count === 0) {
    return {
      className: 'bg-muted/50',
      short: '',
      description: `${when}: no runs recorded`,
    }
  }
  if (broken > 0) {
    const everything = broken === run_count
    return {
      className: everything ? 'bg-severity-severe text-white' : 'bg-severity-major text-white',
      short: formatCount(broken),
      description: `${when}: ${formatCount(broken)} of ${formatCount(run_count)} runs did not finish their work`,
    }
  }
  if (partial_count > 0) {
    return {
      className: 'bg-severity-minor text-foreground',
      short: formatCount(partial_count),
      description: `${when}: ${formatCount(partial_count)} of ${formatCount(run_count)} runs finished with something missing`,
    }
  }
  if (skipped_count === run_count) {
    return {
      className: 'bg-severity-unknown text-foreground',
      short: formatCount(skipped_count),
      description: `${when}: all ${formatCount(run_count)} runs were skipped because the job was already running`,
    }
  }
  return {
    className: 'bg-severity-on-time text-white',
    short: formatCount(run_count),
    description: `${when}: all ${formatCount(run_count)} runs succeeded`,
  }
}
