import { Link } from 'react-router-dom'

import { Container, PageHeader } from '@/components/common'
import { Prose } from '@/components/Prose'
import { useDocumentTitle } from '@/lib/useDocumentTitle'

// The "How it works" page: where the data comes from, the order in which it is processed, what each
// figure on the site means, and the known limitations.
export function MethodologyPage() {
  useDocumentTitle('How it works')
  return (
    <Container>
      <PageHeader
        title="How it works"
        description="Where Linecheck's numbers come from and exactly what they mean."
      />
      <Prose>
        <h2>Where the data comes from</h2>
        <p>
          The MBTA publishes two kinds of open data. The <strong>timetable</strong> (GTFS) lists every trip
          and the time it is scheduled at each stop. The <strong>live feeds</strong> (GTFS-Realtime) report
          where each vehicle is and when it is predicted to reach its upcoming stops. Linecheck reads both
          directly from the MBTA.
        </p>

        <h2>How the data is processed</h2>
        <ol>
          <li>Once a day, the latest MBTA timetable is downloaded and stored.</li>
          <li>
            Every minute, the positions of all vehicles and their predicted arrivals are downloaded. Each
            vehicle&apos;s delay is its predicted arrival at its next stop minus that stop&apos;s scheduled time.
          </li>
          <li>
            Every 5 minutes, recent positions are turned into arrival times at each stop. The live feed never
            says when a vehicle reached a stop, only where it is at each check, so the arrival is estimated
            between two checks: the midpoint when the vehicle is seen stopped there, or a point based on the
            timetable when it passed the stop between checks. The estimate is off by at most one minute.
          </li>
          <li>
            At 15 minutes past each hour, arrivals from the previous hours are summarized per line, direction,
            and hour.
          </li>
          <li>Once a day, old records are removed so storage stays bounded.</li>
        </ol>

        <h2>What the numbers mean</h2>
        <dl>
          <dt>On time</dt>
          <dd>An arrival between 1 minute early and 5 minutes late compared with the timetable.</dd>
          <dt>Delay status</dt>
          <dd>
            Early (more than 1 minute early), on time, minor delay (up to 10 minutes late), major delay (up to
            20 minutes late), severe delay (over 20 minutes late), or no estimate. A line&apos;s status uses the
            median delay of its vehicles, so one very late bus does not mark a whole line as severe.
          </dd>
          <dt>Typical delay</dt>
          <dd>
            The average size of the delay whether early or late, so a line that runs early does not look
            better than one that runs on time.
          </dd>
          <dt>Gap between vehicles (headway)</dt>
          <dd>The time between one vehicle and the next arriving at the same stop in the same direction.</dd>
          <dt>Spacing regularity (CV)</dt>
          <dd>
            How much those gaps vary, as the standard deviation divided by the average gap. 0 means perfectly
            even; higher values mean vehicles are bunching together and then leaving long gaps.
          </dd>
          <dt>Extra wait from uneven spacing</dt>
          <dd>
            How much longer a rider who turns up at a random time waits, on average, because gaps are uneven
            compared with the gaps the timetable planned. It is only measured for service every 15 minutes or
            more often, because riders of less frequent service plan around the timetable.
          </dd>
          <dt>Rankings</dt>
          <dd>
            Lines are compared over complete hours with both directions combined. Busier hours count for more.
            Lines with too few observations are left out so a line seen only a handful of times cannot top the
            list by luck.
          </dd>
        </dl>

        <h2>Known limitations</h2>
        <ul>
          <li>Cancelled trips are not recorded yet, so no figure counts them.</li>
          <li>
            Trips the MBTA adds outside the timetable, which is common for subway service and shuttle buses,
            have no scheduled times to compare against, so they get no delay estimate.
          </li>
          <li>Statistics only cover the time Linecheck has been collecting data.</li>
        </ul>
        <p>
          The current state of each processing step is on the <Link to="/status">status page</Link>.
        </p>
      </Prose>
    </Container>
  )
}
