import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { api, type HistoricalParams, type RankingsParams, type Route } from '@/lib/api'

// Live data changes every minute on the server; pages showing it refresh this often.
export const LIVE_REFRESH_MS = 30_000

// The key that identifies a route across the whole site. Route ids are only unique inside one
// agency, so the agency slug is part of the key.
export function routeKey(agency: string, routeId: string): string {
  return `${agency}:${routeId}`
}

// The cities Linecheck covers. They only change when the server's configuration changes.
export function useRegions() {
  return useQuery({ queryKey: ['regions'], queryFn: api.regions, staleTime: 5 * 60 * 1000 })
}

// All routes in one city. Timetables change at most once a day, so the list is kept for an hour.
export function useRegionRoutes(region: string) {
  return useQuery({
    queryKey: ['region-routes', region],
    queryFn: () => api.regionRoutes(region),
    staleTime: 60 * 60 * 1000,
  })
}

// A map from routeKey(agency, route id) to route for one city, for showing names and colors on
// pages that only have ids.
export function useRouteLookup(region: string): Map<string, Route> {
  const { data } = useRegionRoutes(region)
  return useMemo(
    () => new Map((data ?? []).map((route) => [routeKey(route.agency, route.route_id), route])),
    [data],
  )
}

// A city's live snapshot, refreshed every LIVE_REFRESH_MS. Pass enabled=false for a city whose live
// feeds are not connected, so no pointless requests are made.
export function useRegionLive(region: string, enabled = true) {
  return useQuery({
    queryKey: ['region-live', region],
    queryFn: () => api.regionLive(region),
    refetchInterval: LIVE_REFRESH_MS,
    enabled,
  })
}

// Live vehicles on one route (optionally one direction), refreshed every LIVE_REFRESH_MS.
export function useLiveRoute(agency: string, routeId: string, directionId?: number) {
  return useQuery({
    queryKey: ['live-route', agency, routeId, directionId ?? 'both'],
    queryFn: () => api.liveRoute(agency, routeId, directionId),
    refetchInterval: LIVE_REFRESH_MS,
  })
}

// One route's weekly grid for a date range. Hourly figures only change once an hour.
export function useHistoricalRoute(agency: string, routeId: string, params: HistoricalParams) {
  return useQuery({
    queryKey: ['historical-route', agency, routeId, params],
    queryFn: () => api.historicalRoute(agency, routeId, params),
    staleTime: 5 * 60 * 1000,
  })
}

// A city's route rankings for the given metric and filters. Pass enabled=false to skip the request.
export function useRankings(region: string, params: RankingsParams, enabled = true) {
  return useQuery({
    queryKey: ['rankings', region, params],
    queryFn: () => api.rankings(region, params),
    staleTime: 5 * 60 * 1000,
    enabled,
  })
}

// Alerts in force in one city. Agencies write these by hand, so they are polled far less often than
// vehicles: every two minutes is plenty and keeps the page from hammering the API.
export function useRegionAlerts(region: string) {
  return useQuery({
    queryKey: ['region-alerts', region],
    queryFn: () => api.regionAlerts(region),
    refetchInterval: 2 * 60 * 1000,
  })
}

// Alerts in force on one line, including the agency's service-wide ones.
export function useRouteAlerts(agency: string, routeId: string) {
  return useQuery({
    queryKey: ['route-alerts', agency, routeId],
    queryFn: () => api.routeAlerts(agency, routeId),
    refetchInterval: 2 * 60 * 1000,
  })
}

// Service health, refreshed every LIVE_REFRESH_MS.
export function useHealth() {
  return useQuery({ queryKey: ['health'], queryFn: api.health, refetchInterval: LIVE_REFRESH_MS })
}
