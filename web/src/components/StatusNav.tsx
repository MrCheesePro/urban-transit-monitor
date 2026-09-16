import { NavLink } from 'react-router-dom'

import { cn } from '@/lib/utils'

// The two views of the same subject: what the background jobs are doing now, and what they have
// been doing. Kept out of the main navigation, which is for the transit sections a visitor came
// for, and shown on both status pages so either one leads to the other.
export function StatusNav() {
  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'rounded-sm border px-3 py-1.5 text-sm font-medium',
      isActive
        ? 'border-foreground bg-foreground text-background'
        : 'border-border bg-card text-muted-foreground hover:text-foreground',
    )

  return (
    <nav aria-label="Service status" className="mt-6">
      <ul className="flex flex-wrap gap-2">
        <li>
          <NavLink to="/status" end className={linkClass}>
            Now
          </NavLink>
        </li>
        <li>
          <NavLink to="/status/history" className={linkClass}>
            History
          </NavLink>
        </li>
      </ul>
    </nav>
  )
}
