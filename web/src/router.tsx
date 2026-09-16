import { createBrowserRouter } from 'react-router-dom'

import { RegionLayout } from '@/components/layout/RegionLayout'
import { SiteLayout } from '@/components/layout/SiteLayout'
import { AlertsPage } from '@/pages/AlertsPage'
import { HomePage } from '@/pages/HomePage'
import { LineHistoryPage } from '@/pages/LineHistoryPage'
import { LineLivePage } from '@/pages/LineLivePage'
import { LinesPage } from '@/pages/LinesPage'
import { MethodologyPage } from '@/pages/MethodologyPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { PrivacyPage } from '@/pages/PrivacyPage'
import { RankingsPage } from '@/pages/RankingsPage'
import { RegionHomePage } from '@/pages/RegionHomePage'
import { StatusPage } from '@/pages/StatusPage'
import { TermsPage } from '@/pages/TermsPage'

// Every page of the site and its address. SiteLayout wraps all of them with the header and footer.
// City pages live under the city's slug (/boston/lines, /los-angeles/rankings), and a line's address
// includes its agency because route ids are only unique inside one agency. Fixed paths such as
// /status always win over the city slug pattern.
export const router = createBrowserRouter([
  {
    element: <SiteLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'status', element: <StatusPage /> },
      { path: 'how-it-works', element: <MethodologyPage /> },
      { path: 'privacy', element: <PrivacyPage /> },
      { path: 'terms', element: <TermsPage /> },
      {
        path: ':region',
        element: <RegionLayout />,
        children: [
          { index: true, element: <RegionHomePage /> },
          { path: 'lines', element: <LinesPage /> },
          { path: 'lines/:agency/:routeId', element: <LineLivePage /> },
          { path: 'lines/:agency/:routeId/history', element: <LineHistoryPage /> },
          { path: 'rankings', element: <RankingsPage /> },
          { path: 'service-news', element: <AlertsPage /> },
          { path: '*', element: <NotFoundPage /> },
        ],
      },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
