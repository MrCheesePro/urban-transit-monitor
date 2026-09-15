import { Outlet, useParams } from 'react-router-dom'

import { Container, ErrorPanel, LoadingPanel } from '@/components/common'
import type { Region } from '@/lib/api'
import { useRegions } from '@/lib/queries'
import { NotFoundPage } from '@/pages/NotFoundPage'

// Wraps every city page (/boston/..., /los-angeles/...). It looks up the city named in the address,
// shows the not-found page for an unknown city, and hands the city to the page through the router's
// outlet context (read it with useRegion).
export function RegionLayout() {
  const { region: slug = '' } = useParams()
  const regions = useRegions()

  if (regions.isPending) {
    return (
      <Container className="pt-10">
        <LoadingPanel rows={4} label="Loading city" />
      </Container>
    )
  }
  if (regions.isError) {
    return (
      <Container className="pt-10">
        <ErrorPanel what="the list of cities" error={regions.error} onRetry={() => void regions.refetch()} />
      </Container>
    )
  }
  const region = regions.data.find((candidate) => candidate.slug === slug)
  if (!region) return <NotFoundPage />
  return <Outlet context={region satisfies Region} />
}
