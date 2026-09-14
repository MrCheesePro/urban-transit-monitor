import { useEffect } from 'react'
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMap } from 'react-leaflet'

import type { LiveVehicle } from '@/lib/api'
import { SEVERITY_HEX, SEVERITY_LABELS, signedDelay } from '@/lib/format'

const BOSTON_CENTER: [number, number] = [42.3601, -71.0589]

// Move the map so every vehicle is in view. It only re-fits when `fitKey` changes (a different
// route or direction), so the 30-second refresh never undoes the reader's own zooming.
function FitToVehicles({ points, fitKey }: { points: [number, number][]; fitKey: string }) {
  const map = useMap()
  const hasPoints = points.length > 0
  useEffect(() => {
    if (!hasPoints) return
    if (points.length === 1) map.setView(points[0], 14)
    else map.fitBounds(points, { padding: [32, 32], maxZoom: 15 })
    // Only re-fit for a new route or direction, not for every position update.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, fitKey, hasPoints])
  return null
}

// A map of the vehicles on a route, one dot per vehicle colored by its delay severity, with the
// vehicle number and delay on hover or focus. Map tiles come from OpenStreetMap. Scroll-wheel zoom
// is off so scrolling down the page never gets captured by the map.
export function VehicleMap({ vehicles, fitKey }: { vehicles: LiveVehicle[]; fitKey: string }) {
  const placed = vehicles.filter(
    (vehicle): vehicle is LiveVehicle & { lat: number; lon: number } =>
      vehicle.lat !== null && vehicle.lon !== null,
  )
  const points = placed.map((vehicle): [number, number] => [vehicle.lat, vehicle.lon])

  return (
    <div className="overflow-hidden rounded-md border border-border">
      <MapContainer
        center={BOSTON_CENTER}
        zoom={12}
        scrollWheelZoom={false}
        className="h-[380px] w-full"
        aria-label={`Map of ${placed.length} vehicles`}
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <FitToVehicles points={points} fitKey={fitKey} />
        {placed.map((vehicle) => (
          <CircleMarker
            key={vehicle.vehicle_id}
            center={[vehicle.lat, vehicle.lon]}
            radius={7}
            pathOptions={{
              color: '#F8FAF9',
              weight: 2,
              fillColor: SEVERITY_HEX[vehicle.severity],
              fillOpacity: 1,
            }}
          >
            <Tooltip>
              Vehicle {vehicle.label ?? vehicle.vehicle_id}: {SEVERITY_LABELS[vehicle.severity]} (
              {signedDelay(vehicle.delay_seconds)})
            </Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  )
}
