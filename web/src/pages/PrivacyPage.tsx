import { Container, PageHeader } from '@/components/common'
import { Prose } from '@/components/Prose'
import { ISSUES_URL, OWNER_NAME, POLICY_EFFECTIVE_DATE } from '@/lib/site'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// The Privacy Policy page: what information the site does and does not collect, which third party
// the browser contacts (OpenStreetMap map images), and how to ask questions.
export function PrivacyPage() {
  useDocumentTitle('Privacy Policy')
  return (
    <Container>
      <PageHeader title="Privacy Policy" description={`Effective ${POLICY_EFFECTIVE_DATE}.`} />
      <Prose>
        <h2>Who runs Linecheck</h2>
        <p>
          Linecheck is an independent project run by {OWNER_NAME}. It is not operated by, affiliated with, or
          endorsed by the Massachusetts Bay Transportation Authority (MBTA) or the Los Angeles County
          Metropolitan Transportation Authority (LA Metro).
        </p>

        <h2>Information we collect</h2>
        <p>
          Linecheck has no accounts, sign-up forms, comments, advertising, or analytics. The site does not ask
          you for personal information and does not set cookies or store anything in your browser.
        </p>

        <h2>Server logs</h2>
        <p>
          Like most websites, the server that runs Linecheck may keep standard request logs. These include your
          IP address, the page requested, the time of the request, and your browser&apos;s user agent. They are
          used only to keep the service working and to fix problems, and they are not sold or shared.
        </p>

        <h2>Maps and other services</h2>
        <p>
          Line pages show a map. The map images are loaded directly from OpenStreetMap&apos;s tile servers, so
          when a map is displayed your browser sends your IP address and browser details to OpenStreetMap. That
          information is handled under the{' '}
          <a href="https://osmfoundation.org/wiki/Privacy_Policy" target="_blank" rel="noreferrer">
            OpenStreetMap Foundation Privacy Policy
          </a>
          . Fonts and all other files are served by Linecheck itself.
        </p>

        <h2>Transit data</h2>
        <p>
          The vehicle and timetable data shown on this site comes from the public feeds of the MBTA and LA
          Metro. Linecheck&apos;s server downloads it directly; your browser never contacts those agencies. It
          describes buses, trains, and ferries, not the people riding them.
        </p>

        <h2>Children</h2>
        <p>Linecheck is a general information site and is not directed at children.</p>

        <h2>Changes to this policy</h2>
        <p>
          If this policy changes, the updated version will be posted on this page with a new effective date.
        </p>

        <h2>Contact</h2>
        <p>
          Questions about this policy can be raised by opening an issue on the{' '}
          <a href={ISSUES_URL} target="_blank" rel="noreferrer">
            Linecheck GitHub repository
          </a>
          .
        </p>
      </Prose>
    </Container>
  )
}
