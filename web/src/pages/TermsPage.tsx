import { Link } from 'react-router-dom'

import { Container, PageHeader } from '@/components/common'
import { Prose } from '@/components/Prose'
import { ISSUES_URL, OWNER_NAME, POLICY_EFFECTIVE_DATE } from '@/lib/site'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// The Terms & Conditions page: what the site is, that its figures are estimates provided without
// warranty, the relationship to the MBTA and OpenStreetMap, acceptable use, and how to get in touch.
export function TermsPage() {
  useDocumentTitle('Terms & Conditions')
  return (
    <Container>
      <PageHeader title="Terms & Conditions" description={`Effective ${POLICY_EFFECTIVE_DATE}.`} />
      <Prose>
        <h2>About these terms</h2>
        <p>
          Linecheck is an independent project run by {OWNER_NAME}. By using this site you agree to these terms.
          If you do not agree, please do not use the site.
        </p>

        <h2>Information only</h2>
        <p>
          Delays, arrival times, and statistics on Linecheck are estimates calculated from the public data of
          the transit agencies it covers. They can be incomplete, delayed, or wrong, for example when an
          agency&apos;s feeds are unavailable. Do not rely on Linecheck when timing matters; check official
          sources such as{' '}
          <a href="https://www.mbta.com" target="_blank" rel="noreferrer">
            mbta.com
          </a>{' '}
          or{' '}
          <a href="https://www.metro.net" target="_blank" rel="noreferrer">
            metro.net
          </a>{' '}
          before you travel. <Link to="/how-it-works">How it works</Link> explains how each figure is calculated.
        </p>

        <h2>No warranty</h2>
        <p>
          The site is provided &quot;as is&quot; and &quot;as available&quot;, without warranties of any kind,
          including accuracy, availability, or fitness for a particular purpose.
        </p>

        <h2>Limitation of liability</h2>
        <p>
          To the fullest extent permitted by law, {OWNER_NAME} is not liable for any loss or damage arising from
          your use of the site or from relying on the information it shows, including missed connections or
          travel delays.
        </p>

        <h2>Relationship to the transit agencies</h2>
        <p>
          Linecheck is not affiliated with or endorsed by the MBTA, LA Metro, LADOT Transit, Long Beach
          Transit, Torrance Transit or OCTA. Line names and line colors are used only to identify each agency&apos;s
          services. Transit data is provided by those agencies and is subject to their own terms for
          developers, described at{' '}
          <a href="https://www.mbta.com/developers" target="_blank" rel="noreferrer">
            mbta.com/developers
          </a>{' '}
          and{' '}
          <a href="https://developer.metro.net" target="_blank" rel="noreferrer">
            developer.metro.net
          </a>
          .
        </p>

        <h2>Map data</h2>
        <p>
          Maps use data and images from{' '}
          <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
            OpenStreetMap contributors
          </a>
          , available under the Open Database License.
        </p>

        <h2>Acceptable use</h2>
        <p>
          Please do not use automated tools to request pages or data from Linecheck at a rate that could slow the
          service down for others, and do not try to disrupt or gain unauthorized access to the service.
        </p>

        <h2>Changes to these terms</h2>
        <p>
          These terms may be updated. The current version is always on this page with its effective date.
        </p>

        <h2>Contact</h2>
        <p>
          Questions about these terms can be raised by opening an issue on the{' '}
          <a href={ISSUES_URL} target="_blank" rel="noreferrer">
            Linecheck GitHub repository
          </a>
          .
        </p>
      </Prose>
    </Container>
  )
}
