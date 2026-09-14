import { NavLink, Outlet, ScrollRestoration, Link } from 'react-router-dom'

import { Logo } from '@/components/brand/Logo'
import { OWNER_NAME, REPOSITORY_URL } from '@/lib/site'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/lines', label: 'Lines' },
  { to: '/rankings', label: 'Rankings' },
  { to: '/status', label: 'Status' },
  { to: '/how-it-works', label: 'How it works' },
]

// Top bar on every page: the logo (a link home) and the main navigation. The current section is
// marked with a solid bar under its link, like the lit segment of a line diagram. On narrow screens
// the navigation scrolls sideways instead of hiding behind a menu button.
function SiteHeader() {
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <Link to="/" className="self-start rounded-sm" aria-label="Linecheck home">
          <Logo />
        </Link>
        <nav aria-label="Main" className="-mx-1 overflow-x-auto">
          <ul className="flex gap-1">
            {NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  className={({ isActive }) =>
                    cn(
                      'block whitespace-nowrap rounded-sm border-b-[3px] px-3 py-2 text-sm font-medium transition-colors',
                      isActive
                        ? 'border-foreground text-foreground'
                        : 'border-transparent text-muted-foreground hover:text-foreground',
                    )
                  }
                >
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  )
}

// Bottom of every page: legal and information links, the data source, and the independence note.
function SiteFooter() {
  const year = new Date().getFullYear()
  return (
    <footer className="mt-16 border-t border-border bg-card">
      <div className="mx-auto grid w-full max-w-6xl gap-6 px-4 py-8 text-sm sm:grid-cols-2 sm:px-6">
        <div className="space-y-2 text-muted-foreground">
          <p>
            Transit data comes from the MBTA&apos;s public GTFS and GTFS-Realtime feeds. Linecheck is an
            independent project and is not affiliated with or endorsed by the MBTA.
          </p>
          <p>
            &copy; {year} {OWNER_NAME}
          </p>
        </div>
        <nav aria-label="Footer" className="sm:justify-self-end">
          <ul className="grid grid-cols-2 gap-x-8 gap-y-2">
            <li>
              <Link className="underline-offset-4 hover:underline" to="/privacy">
                Privacy Policy
              </Link>
            </li>
            <li>
              <Link className="underline-offset-4 hover:underline" to="/terms">
                Terms &amp; Conditions
              </Link>
            </li>
            <li>
              <Link className="underline-offset-4 hover:underline" to="/how-it-works">
                How it works
              </Link>
            </li>
            <li>
              <Link className="underline-offset-4 hover:underline" to="/status">
                Service status
              </Link>
            </li>
            <li>
              <a
                className="underline-offset-4 hover:underline"
                href={REPOSITORY_URL}
                target="_blank"
                rel="noreferrer"
              >
                Source code on GitHub
              </a>
            </li>
          </ul>
        </nav>
      </div>
    </footer>
  )
}

// The frame shared by every page: a skip link for keyboard users, the header, the page content,
// and the footer. ScrollRestoration returns to the top when moving to a new page.
export function SiteLayout() {
  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[1000] focus:rounded-sm focus:bg-card focus:px-3 focus:py-2"
      >
        Skip to content
      </a>
      <SiteHeader />
      <main id="main" className="flex-1">
        <Outlet />
      </main>
      <SiteFooter />
      <ScrollRestoration />
    </div>
  )
}
