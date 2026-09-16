import type { Route, Severity } from '@/lib/api'

// GTFS route_type codes and the names riders use for them.
export const MODE_NAMES: Record<number, string> = {
  0: 'Light rail',
  1: 'Subway',
  2: 'Commuter rail',
  3: 'Bus',
  4: 'Ferry',
}

// The order modes appear on the site: rapid transit first, then commuter rail, buses, and ferries.
export const MODE_ORDER = [1, 0, 2, 3, 4]

export const SEVERITY_ORDER: Severity[] = ['on_time', 'early', 'minor', 'major', 'severe', 'unknown']

export const SEVERITY_LABELS: Record<Severity, string> = {
  on_time: 'On time',
  early: 'Early',
  minor: 'Minor delay',
  major: 'Major delay',
  severe: 'Severe delay',
  unknown: 'No estimate',
}

// Full Tailwind class names per severity (written out in full so Tailwind includes them).
export const SEVERITY_BG: Record<Severity, string> = {
  on_time: 'bg-severity-on-time',
  early: 'bg-severity-early',
  minor: 'bg-severity-minor',
  major: 'bg-severity-major',
  severe: 'bg-severity-severe',
  unknown: 'bg-severity-unknown',
}

// The same severity colors as hex values, for places that cannot use CSS classes (the map).
export const SEVERITY_HEX: Record<Severity, string> = {
  on_time: '#2e7d5b',
  early: '#3d6fb6',
  minor: '#b7830a',
  major: '#c65214',
  severe: '#9e1b2f',
  unknown: '#8a918e',
}

// GTFS-Realtime alert causes in plain English. Codes an agency leaves as unknown are not listed,
// because "unknown cause" tells a reader nothing worth a line on screen.
const ALERT_CAUSES: Record<string, string> = {
  ACCIDENT: 'Crash',
  CONSTRUCTION: 'Construction',
  DEMONSTRATION: 'Demonstration',
  HOLIDAY: 'Holiday',
  MAINTENANCE: 'Maintenance',
  MEDICAL_EMERGENCY: 'Medical emergency',
  POLICE_ACTIVITY: 'Police activity',
  STRIKE: 'Strike',
  TECHNICAL_PROBLEM: 'Technical problem',
  WEATHER: 'Weather',
}

// GTFS-Realtime alert effects in plain English, for example what the alert does to service.
const ALERT_EFFECTS: Record<string, string> = {
  ACCESSIBILITY_ISSUE: 'Accessibility issue',
  ADDITIONAL_SERVICE: 'Extra service',
  DETOUR: 'Detour',
  MODIFIED_SERVICE: 'Changed service',
  NO_SERVICE: 'No service',
  REDUCED_SERVICE: 'Reduced service',
  SIGNIFICANT_DELAYS: 'Significant delays',
  STOP_MOVED: 'Stop moved',
}

// The cause of an alert in plain English, or null when the agency did not give a usable one.
export function alertCause(cause: string | null | undefined): string | null {
  return cause ? (ALERT_CAUSES[cause] ?? null) : null
}

// What an alert does to service, in plain English, or null when the agency did not say.
export function alertEffect(effect: string | null | undefined): string | null {
  return effect ? (ALERT_EFFECTS[effect] ?? null) : null
}

// Name of a mode of transport from its GTFS route_type, for example 3 gives "Bus".
export function modeName(routeType: number | null | undefined): string {
  if (routeType === null || routeType === undefined) return 'Other service'
  return MODE_NAMES[routeType] ?? 'Other service'
}

type NamedRoute = Pick<Route, 'route_id' | 'route_short_name' | 'route_long_name' | 'route_type'>

// Whether a bus route's short name is a route number such as "39", "SL1", or "10/48" rather than a
// whole name such as LA Metro's "Dodger Stadium Express".
function isRouteNumber(shortName: string): boolean {
  return /^[\w/-]{1,8}$/.test(shortName)
}

// The name riders know a route by: "Route 1" for numbered buses, a named bus service as it is
// written ("Dodger Stadium Express"), "Red Line" or "Metro A Line" for rail, or the id as a last
// resort.
export function routeName(route: NamedRoute | undefined, fallbackId = 'Unknown route'): string {
  if (!route) return fallbackId
  const shortName = route.route_short_name
  if (route.route_type === 3 && shortName) {
    return isRouteNumber(shortName) ? `Route ${shortName}` : shortName
  }
  return route.route_long_name || shortName || route.route_id
}

// Short text for a route badge: the bus number ("39", "SL1", "720"), "CR" for commuter rail,
// "Ferry" for boats, the line letter of an LA Metro line ("A" for "Metro A Line"), or otherwise the
// first word of the line's name when it is short ("Red", "Mattapan"). Long names become initials
// ("DSE" for "Dodger Stadium Express"). Never cuts a word in half.
export function badgeLabel(route: NamedRoute | undefined, routeId: string): string {
  const shortName = route?.route_short_name
  if (shortName && isRouteNumber(shortName)) return shortName
  if (route?.route_type === 2) return 'CR'
  if (route?.route_type === 4) return 'Ferry'
  const lineLetter = route?.route_long_name?.match(/^Metro (\w{1,3}) Line$/)
  if (lineLetter) return lineLetter[1]
  const firstWord = route?.route_long_name?.split(' ')[0]
  if (firstWord && firstWord.length <= 8) return firstWord
  const initials = (shortName || route?.route_long_name || routeId)
    .split(/[\s/-]+/)
    .filter(Boolean)
    .map((word) => word[0].toUpperCase())
    .join('')
  return initials.slice(0, 4)
}

// A timetable color as "#RRGGBB", or null when the value is missing or not a 6-digit hex code.
export function hexColor(value: string | null | undefined): string | null {
  return value && /^[0-9a-fA-F]{6}$/.test(value) ? `#${value}` : null
}

// Minutes and seconds without a sign, for example 200 gives "3:20".
function minutesAndSeconds(totalSeconds: number): string {
  const seconds = Math.abs(Math.round(totalSeconds))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

// A delay in words: "3 min 20 s late", "45 s early", "On schedule", or "No estimate".
export function describeDelay(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'No estimate'
  const rounded = Math.round(seconds)
  if (rounded === 0) return 'On schedule'
  const size = Math.abs(rounded)
  const minutes = Math.floor(size / 60)
  const rest = size % 60
  const amount = minutes > 0 ? `${minutes} min${rest ? ` ${rest} s` : ''}` : `${rest} s`
  return `${amount} ${rounded > 0 ? 'late' : 'early'}`
}

// A compact signed delay for tables: "+3:20" late, "-0:45" early, "0:00", or "n/a".
export function signedDelay(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'n/a'
  const rounded = Math.round(seconds)
  const sign = rounded > 0 ? '+' : rounded < 0 ? '-' : ''
  return `${sign}${minutesAndSeconds(rounded)}`
}

// A length of time: seconds under a minute ("45 s"), otherwise rounded minutes ("10 min"), or hours
// and minutes from an hour up ("2 h 15 min").
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'n/a'
  const rounded = Math.round(seconds)
  if (rounded < 60) return `${rounded} s`
  const minutes = Math.round(rounded / 60)
  if (minutes < 60) return `${minutes} min`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

// A percentage with one decimal place, for example 86.04 gives "86.0%".
export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? 'n/a' : `${value.toFixed(1)}%`
}

// A headway coefficient of variation with two decimal places, for example 0.304 gives "0.30".
export function formatCv(value: number | null | undefined): string {
  return value === null || value === undefined ? 'n/a' : value.toFixed(2)
}

// A whole number with thousands separators, for example 12840 gives "12,840".
export function formatCount(value: number): string {
  return value.toLocaleString('en-US')
}

// How long ago something happened, for example 45 gives "45 s ago".
export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'never'
  return `${formatDuration(Math.max(0, seconds))} ago`
}

// Seconds between an ISO timestamp and now.
export function secondsSince(iso: string): number {
  return Math.round((Date.now() - new Date(iso).getTime()) / 1000)
}

// Clock time for an ISO timestamp in a time zone such as "America/Los_Angeles", for example
// "4:12 PM". Without a time zone it uses the reader's own.
export function localTime(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return 'n/a'
  return new Intl.DateTimeFormat('en-US', {
    timeZone,
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(iso))
}

// Date and clock time for an ISO timestamp in a time zone, for example "Sep 14, 4:12 PM". Without a
// time zone it uses the reader's own.
export function localDateTime(iso: string | null | undefined, timeZone?: string): string {
  if (!iso) return 'n/a'
  return new Intl.DateTimeFormat('en-US', {
    timeZone,
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(iso))
}

// Today's date in a time zone as YYYY-MM-DD, the format the API expects for date ranges.
export function todayIn(timeZone: string): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone }).format(new Date())
}

// A YYYY-MM-DD date moved by a number of days (negative moves back).
export function shiftDate(date: string, days: number): string {
  const moved = new Date(`${date}T12:00:00Z`)
  moved.setUTCDate(moved.getUTCDate() + days)
  return moved.toISOString().slice(0, 10)
}

// A YYYY-MM-DD date written out for people, for example "Sep 14, 2026".
export function readableDate(date: string): string {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'UTC',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(`${date}T12:00:00Z`))
}
