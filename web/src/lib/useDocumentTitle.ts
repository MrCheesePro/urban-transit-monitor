import { useEffect } from 'react'

// Set the browser tab title for the current page, for example "Rankings | Linecheck". Pass null on
// the home page to use the full site title.
export function useDocumentTitle(title: string | null) {
  useEffect(() => {
    document.title = title ? `${title} | Linecheck` : 'Linecheck: MBTA line reliability'
  }, [title])
}
