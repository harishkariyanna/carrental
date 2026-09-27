import { useEffect, useState } from 'react'
import L from 'leaflet'
import { MapContainer, Marker, Polyline, TileLayer, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { api } from '../../api'

export interface MapPoint { latitude: number; longitude: number; label?: string }

const marker = (color: string) => L.divIcon({ className: '', html: `<span style="display:block;width:18px;height:18px;border:4px solid white;border-radius:50%;background:${color};box-shadow:0 2px 8px #243b5a66"></span>`, iconAnchor: [9, 9] })

function FitMap({ points }: { points: MapPoint[] }) {
  const map = useMap()
  useEffect(() => {
    if (points.length === 1) map.setView([points[0].latitude, points[0].longitude], 14)
    if (points.length > 1) map.fitBounds(L.latLngBounds(points.map((point) => [point.latitude, point.longitude])), { padding: [30, 30] })
  }, [map, points])
  return null
}

export function RouteMap({ pickup, drop, driver, onPickupChange, onDropChange }: { pickup?: MapPoint; drop?: MapPoint; driver?: MapPoint; onPickupChange?: (point: MapPoint) => void; onDropChange?: (point: MapPoint) => void }) {
  const points = [pickup, drop, driver].filter(Boolean) as MapPoint[]
  const center = points[0] ?? { latitude: 12.9716, longitude: 77.5946 }
  const [route, setRoute] = useState<Array<[number, number]>>([])
  const pickupLat = pickup?.latitude
  const pickupLng = pickup?.longitude
  const dropLat = drop?.latitude
  const dropLng = drop?.longitude
  useEffect(() => {
    if (pickupLat === undefined || pickupLng === undefined || dropLat === undefined || dropLng === undefined) return
    let cancelled = false
    const params = new URLSearchParams({ pickup_lat: String(pickupLat), pickup_lng: String(pickupLng), drop_lat: String(dropLat), drop_lng: String(dropLng) })
    void api<{ coordinates: Array<[number, number]> }>(`/maps/route?${params}`).then((result) => {
      if (!cancelled) setRoute(result.coordinates)
    }).catch(() => {
      if (!cancelled) setRoute([[pickupLat, pickupLng], [dropLat, dropLng]])
    })
    return () => { cancelled = true }
  }, [pickupLat, pickupLng, dropLat, dropLng])
  return <MapContainer center={[center.latitude, center.longitude]} zoom={12} className="route-map" scrollWheelZoom>
    <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
    {pickup && <Marker draggable={Boolean(onPickupChange)} icon={marker('#0867f2')} position={[pickup.latitude, pickup.longitude]} eventHandlers={{ dragend: (event) => { const point = event.target.getLatLng(); onPickupChange?.({ latitude: point.lat, longitude: point.lng, label: pickup.label }) } }} />}
    {drop && <Marker draggable={Boolean(onDropChange)} icon={marker('#e34444')} position={[drop.latitude, drop.longitude]} eventHandlers={{ dragend: (event) => { const point = event.target.getLatLng(); onDropChange?.({ latitude: point.lat, longitude: point.lng, label: drop.label }) } }} />}
    {driver && <Marker icon={marker('#0aa66f')} position={[driver.latitude, driver.longitude]} />}
    {route.length > 1 && <Polyline positions={route} pathOptions={{ color: '#0867f2', weight: 5 }} />}
    <FitMap points={points} />
  </MapContainer>
}

export function LocationSearch({ label, value, point, onSelect }: { label: string; value: string; point?: MapPoint; onSelect: (label: string, point?: MapPoint) => void }) {
  const [results, setResults] = useState<Array<{label:string;latitude:number;longitude:number}>>([])
  const [loading, setLoading] = useState(false)
  const search = async () => {
    setLoading(true)
    try { setResults(await api(`/maps/geocode?q=${encodeURIComponent(value)}`)) } finally { setLoading(false) }
  }
  return <div className="location-search"><label className="field"><span>{label}</span><div><input value={value} onChange={(event) => onSelect(event.target.value, point)} required /><button type="button" onClick={search}>{loading ? '...' : 'Search'}</button></div></label>{results.length>0&&<div className="location-results">{results.map((result)=><button type="button" key={`${result.latitude}-${result.longitude}`} onClick={()=>{onSelect(result.label,result);setResults([])}}>{result.label}</button>)}</div>}</div>
}