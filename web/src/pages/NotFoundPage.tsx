import { Link } from 'react-router-dom'

import { Container, PageHeader } from '@/components/common'
import { useRegions } from '@/lib/queries'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// Shown for any address that is not a page on the site, with links back to the home page and to
// each city's lines.
export function NotFoundPage() {
  useDocumentTitle('Page not found')
  const regions = useRegions()
  return (
    <Container>
      <PageHeader title="Page not found" description="There is no page at this address." />
      <ul className="mt-6 space-y-2">
        <li>
          <Link to="/" className="underline underline-offset-4">
            Go to the home page
          </Link>
        </li>
        {(regions.data ?? []).map((region) => (
          <li key={region.slug}>
            <Link to={`/${region.slug}/lines`} className="underline underline-offset-4">
              Browse {region.name} lines
            </Link>
          </li>
        ))}
      </ul>
    </Container>
  )
}
