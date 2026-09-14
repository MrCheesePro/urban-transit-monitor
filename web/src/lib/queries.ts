import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { api, type HistoricalParams, type Route, type RankingsParams } from '@/lib/api'

// Live data changes every minute on the server; pages showing it refresh this often.
export const LIVE_REFRESH_MS = 30_000

// All routes. The timetable changes at most once a day, so the list is kept for an hour.
export function useRoutes() {
  return useQuery({ queryKey: ['routes'], queryFn: api.routes, staleTime: 60 * 60 * 1000 })
}

// A map from route id to route, for showing names and colors on pages that only have route ids.
export function useRouteLookup(): Map<string, Route> {
  const { data } = useRoutes()
  return useMemo(() => new Map((data ?? []).map((route) => [route.route_id, route])), [data])
}

// The whole network's live snapshot, refreshed every LIVE_REFRESH_MS.
export function useSystemLive() {
  return useQuery({
    queryKey: ['system-live'],
    queryFn: api.systemLive,
    refetchInterval: LIVE_REFRESH_MS,
  })
}

// Live vehicles on one route (optionally one direction), refreshed every LIVE_REFRESH_MS.
export function useLiveRoute(routeId: string, directionId?: number) {
  return useQuery({
    queryKey: ['live-route', routeId, directionId ?? 'both'],
    queryFn: () => api.liveRoute(routeId, directionId),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

// One route's weekly grid for a date range. Hourly figures only change once an hour.
export function useHistoricalRoute(routeId: string, params: HistoricalParams) {
  return useQuery({
    queryKey: ['historical-route', routeId, params],
    queryFn: () => api.historicalRoute(routeId, params),
    staleTime: 5 * 60 * 1000,
  })
}

// Route rankings for the given metric and filters.
export function useRankings(params: RankingsParams) {
  return useQuery({
    queryKey: ['rankings', params],
    queryFn: () => api.rankings(params),
    staleTime: 5 * 60 * 1000,
  })
}

// Service health, refreshed every LIVE_REFRESH_MS.
export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: LIVE_REFRESH_MS })
}
