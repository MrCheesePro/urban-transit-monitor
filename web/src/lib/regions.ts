import { useOutletContext } from 'react-router-dom'

import type { Region } from '@/lib/api'

// Map starting points and search hints per city. The map re-centers on the vehicles as soon as there
// are any, so the center only matters for the first moment a map is shown.
const REGION_DETAILS: Record<string, { center: [number, number]; searchExample: string }> = {
  boston: { center: [42.3601, -71.0589], searchExample: 'Red Line, 39, Fitchburg' },
  'los-angeles': { center: [34.0522, -118.2437], searchExample: 'A Line, 720, Dodger' },
  'la-municipal': { center: [33.8722, -118.2437], searchExample: 'DASH, 111, 13' },
  'orange-county': { center: [33.7175, -117.8311], searchExample: '1, 143, 167' },
}

const FALLBACK_DETAILS = { center: [39.5, -98.35] as [number, number], searchExample: 'Line name or number' }

// Where to center a city's map before its vehicles are known.
export function regionCenter(slug: string): [number, number] {
  return (REGION_DETAILS[slug] ?? FALLBACK_DETAILS).center
}

// An example search for a city's lines page, using real line names from that city.
export function regionSearchExample(slug: string): string {
  return (REGION_DETAILS[slug] ?? FALLBACK_DETAILS).searchExample
}

// The address of one line's live page inside a city, for example /los-angeles/lines/lametro-rail/801.
export function linePath(region: string, agency: string, routeId: string): string {
  return `/${region}/lines/${encodeURIComponent(agency)}/${encodeURIComponent(routeId)}`
}

// The display name of one of a city's agencies, for example "LA Metro Rail", or the slug if unknown.
export function agencyName(region: Region, slug: string): string {
  return region.agencies.find((agency) => agency.slug === slug)?.name ?? slug
}

// The city whose pages are being shown. Only works inside RegionLayout, which checks that the city in
// the address exists before rendering any city page.
export function useRegion(): Region {
  return useOutletContext<Region>()
}
