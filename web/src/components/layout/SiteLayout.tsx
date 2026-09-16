import { Link, NavLink, Outlet, ScrollRestoration, useLocation, useMatch } from 'react-router-dom'

import { Logo } from '@/components/brand/Logo'
import { useRegions } from '@/lib/queries'
import { OWNER_NAME, REPOSITORY_URL } from '@/lib/site'
import { cn } from '@/lib/utils'

const NAV_LINK =
  'block whitespace-nowrap rounded-sm border-b-[3px] px-3 py-2 text-sm font-medium transition-colors'

// Class names for a main navigation link, marking the current section with a solid bar underneath.
function navClass({ isActive }: { isActive: boolean }) {
  return cn(
    NAV_LINK,
    isActive
      ? 'border-foreground text-foreground'
      : 'border-transparent text-muted-foreground hover:text-foreground',
  )
}

// The city being viewed (from the address) and the city the Lines and Rankings links point to: the
// current city on city pages, otherwise the first city the API lists. Also works out where each
// city button should go so switching city keeps the reader in the same section (lines or rankings).
function useCityNavigation() {
  const regions = useRegions()
  const match = useMatch({ path: '/:region', end: false })
  const { pathname, search } = useLocation()
  const list = regions.data ?? []
  const current = list.find((region) => region.slug === match?.params.region)
  const target = current?.slug ?? list[0]?.slug

  // The same section of another city: rankings keep their filters, a line page goes to the lines list
  // (the line does not exist in the other city), and anything else goes to the city's overview.
  function switchTo(slug: string): string {
    if (!current) return `/${slug}`
    const rest = pathname.slice(`/${current.slug}`.length)
    if (rest.startsWith('/rankings')) return `/${slug}/rankings${search}`
    if (rest.startsWith('/lines')) return `/${slug}/lines`
    return `/${slug}`
  }

  return { regions: list, current, target, switchTo }
}

// Top bar on every page: the logo (a link home), a city switcher, and the main navigation. The
// current section is marked with a solid bar under its link, like the lit segment of a line diagram.
// On narrow screens the navigation scrolls sideways instead of hiding behind a menu button.
function SiteHeader() {
  const { regions, current, target, switchTo } = useCityNavigation()
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-3 px-4 py-3 lg:flex-row lg:items-center lg:justify-between sm:px-6">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <Link to="/" className="self-start rounded-sm" aria-label="Linecheck home">
            <Logo />
          </Link>
          {regions.length > 1 ? (
            <nav aria-label="City">
              <ul className="flex rounded-sm border border-border">
                {regions.map((region) => {
                  const active = region.slug === current?.slug
                  return (
                    <li key={region.slug} className="border-border not-first:border-l">
                      <Link
                        to={switchTo(region.slug)}
                        aria-current={active ? 'true' : undefined}
                        className={cn(
                          'block whitespace-nowrap px-3 py-1.5 text-sm font-medium',
                          active
                            ? 'bg-foreground text-background'
                            : 'text-muted-foreground hover:text-foreground',
                        )}
                      >
                        {region.name}
                      </Link>
                    </li>
                  )
                })}
              </ul>
            </nav>
          ) : null}
        </div>
        <nav aria-label="Main" className="-mx-1 overflow-x-auto">
          <ul className="flex gap-1">
            {target ? (
              <>
                <li>
                  <NavLink to={`/${target}/lines`} className={navClass}>
                    Lines
                  </NavLink>
                </li>
                <li>
                  <NavLink to={`/${target}/rankings`} className={navClass}>
                    Rankings
                  </NavLink>
                </li>
              </>
            ) : null}
            <li>
              <NavLink to="/status" className={navClass}>
                Status
              </NavLink>
            </li>
            <li>
              <NavLink to="/how-it-works" className={navClass}>
                How it works
              </NavLink>
            </li>
          </ul>
        </nav>
      </div>
    </header>
  )
}

// Bottom of every page: legal and information links, the data sources, and the independence note.
function SiteFooter() {
  const year = new Date().getFullYear()
  return (
    <footer className="mt-16 border-t border-border bg-card">
      <div className="mx-auto grid w-full max-w-6xl gap-6 px-4 py-8 text-sm sm:grid-cols-2 sm:px-6">
        <div className="space-y-2 text-muted-foreground">
          <p>
            Transit data comes from the public GTFS and GTFS-Realtime feeds of the MBTA, LA Metro, LADOT,
            Long Beach Transit and OCTA. Linecheck is an independent project and is not affiliated with or
            endorsed by any of these agencies.
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
