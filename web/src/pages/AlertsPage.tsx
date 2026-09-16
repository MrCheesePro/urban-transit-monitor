import { Link } from 'react-router-dom'

import { AlertsPanel } from '@/components/AlertsPanel'
import { Container, PageHeader } from '@/components/common'
import { useRegionAlerts, useRouteLookup } from '@/lib/queries'
import { useRegion } from '@/lib/regions'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// A city's service news page: every alert its agencies have in force right now, in full, newest
// first. The city page shows only the first few of these and links here for the rest.
export function AlertsPage() {
  const region = useRegion()
  useDocumentTitle(`${region.name} service news`)
  const alerts = useRegionAlerts(region.slug)
  const lookup = useRouteLookup(region.slug)

  return (
    <Container>
      <PageHeader
        eyebrow={region.name}
        title="Service news"
        description={`What ${region.name} operators say is happening on their lines right now. Every word comes from the agency's own alert feed.`}
      />
      <div className="mt-8">
        <AlertsPanel query={alerts} region={region} lookup={lookup} />
      </div>
      <p className="mt-8 text-sm text-muted-foreground">
        Alerts explain service; the figures on this site measure it.{' '}
        <Link to={`/${region.slug}/lines`} className="font-medium underline underline-offset-4">
          Browse {region.name} lines
        </Link>{' '}
        to see how late vehicles actually are.
      </p>
    </Container>
  )
}
