import { createBrowserRouter } from 'react-router-dom'

import { SiteLayout } from '@/components/layout/SiteLayout'
import { HomePage } from '@/pages/HomePage'
import { LineHistoryPage } from '@/pages/LineHistoryPage'
import { LineLivePage } from '@/pages/LineLivePage'
import { LinesPage } from '@/pages/LinesPage'
import { MethodologyPage } from '@/pages/MethodologyPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { PrivacyPage } from '@/pages/PrivacyPage'
import { RankingsPage } from '@/pages/RankingsPage'
import { StatusPage } from '@/pages/StatusPage'
import { TermsPage } from '@/pages/TermsPage'

// Every page of the site and its address. SiteLayout wraps all of them with the header and footer.
export const router = createBrowserRouter([
  {
    element: <SiteLayout />,
    children: [
      { index: true, element: <HomePage /> },
      { path: 'lines', element: <LinesPage /> },
      { path: 'lines/:routeId', element: <LineLivePage /> },
      { path: 'lines/:routeId/history', element: <LineHistoryPage /> },
      { path: 'rankings', element: <RankingsPage /> },
      { path: 'status', element: <StatusPage /> },
      { path: 'how-it-works', element: <MethodologyPage /> },
      { path: 'privacy', element: <PrivacyPage /> },
      { path: 'terms', element: <TermsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
