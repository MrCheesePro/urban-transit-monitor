import { Link } from 'react-router-dom'

import { Container, PageHeader } from '@/components/common'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// Shown for any address that is not a page on the site, with links back to the main pages.
export function NotFoundPage() {
  useDocumentTitle('Page not found')
  return (
    <Container>
      <PageHeader title="Page not found" description="There is no page at this address." />
      <ul className="mt-6 space-y-2">
        <li>
          <Link to="/" className="underline underline-offset-4">
            Go to the home page
          </Link>
        </li>
        <li>
          <Link to="/lines" className="underline underline-offset-4">
            Browse all lines
          </Link>
        </li>
      </ul>
    </Container>
  )
}
