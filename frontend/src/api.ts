const localApiUrl = `${window.location.protocol}//${window.location.hostname}:8000/api/v1`
export const API_URL = import.meta.env.VITE_API_URL ?? localApiUrl
sessionStorage.removeItem('ridex_csrf')
sessionStorage.removeItem('ridex_draft')
document.cookie = 'ridex_csrf=; Max-Age=0; path=/'

export type Role = 'CUSTOMER' | 'ADMIN' | 'SUPER_ADMIN' | 'DRIVER'
export type VehicleType = 'SEDAN_CNG' | 'SEDAN_NON_CNG' | 'SUV' | 'ERTIGA' | 'INNOVA' | 'INNOVA_CRYSTA' | 'TT'

export interface User {
  id: string
  name: string
  email: string
  phone: string
  role: Role
  profile_image_id?: string
}

interface JwtClaims {
  sub: string
  role: Role
  name: string
  email: string
  phone: string
  exp: number
}

export interface Vehicle {
  id: string
  name: string
  registration_number: string
  category: VehicleType
  seats: number
  luggage: number
  transmission: string
  fuel: string
  has_ac: boolean
  rating: number
  base_rate: number
  local_base_fare: number
  local_included_km: number
  local_per_km: number
  local_waiting_grace_minutes: number
  local_waiting_rate_per_minute: number
  outstation_one_way_base_fare: number
  outstation_one_way_per_km: number
  outstation_one_way_included_km_per_day: number
  outstation_one_way_extra_km_rate: number
  outstation_one_way_driver_bata_per_day: number
  outstation_one_way_base_fare_non_ac: number
  outstation_one_way_extra_km_rate_non_ac: number
  outstation_round_trip_day_rate: number
  outstation_included_km_per_day: number
  outstation_extra_km_rate: number
  driver_bata_per_day: number
  outstation_round_trip_day_rate_non_ac: number
  outstation_extra_km_rate_non_ac: number
  image: string
  status: 'ACTIVE' | 'MAINTENANCE' | 'INACTIVE'
  amenities: string[]
}

export interface Quote {
  quote_id: string
  vehicle: Vehicle
  total: number
  currency: string
  expires_at: string
  line_items: { label: string; amount: number }[]
  pricing: {
    distance_km?: number
    one_way_distance_km?: number
    billable_distance_km?: number
    included_distance_km?: number
    estimated_duration_minutes?: number
    trip_days?: number
    coupon_ineligible_reason?: string
    coupon?: { id: string; code: string; discount: number; scope: string }
  }
}

export interface Booking {
  id: string
  public_id: string
  customer_id: string
  vehicle_id: string
  driver_id?: string
  service_type: string
  pickup: string
  destination: string
  scheduled_at: string
  passengers: number
  luggage: number
  passenger_name?: string
  passenger_phone?: string
  pickup_latitude?: number
  pickup_longitude?: number
  drop_latitude?: number
  drop_longitude?: number
  airport_direction?: string
  airport_pickup_at?: string
  waiting_charge?: number
  waiting_started_at?: string
  waiting_grace_minutes?: number
  waiting_rate_per_minute?: number
  paid_amount?: number
  driver_collected_amount?: number
  balance_payment_method?: 'CASH' | 'UPI'
  balance_collected_at?: string
  balance_due?: number
  quoted_total?: number
  extra_total?: number
  package_hours?: number
  status: string
  payment_status: string
  total: number
  currency: string
  line_items?: { label: string; amount: number }[]
  pricing?: Quote['pricing']
  vehicle?: Vehicle
  driver?: User
  driver_location?: { latitude?: number; longitude?: number; last_seen?: string; availability?: string }
}

const JWT_KEY = 'ridex_jwt'

export function setJwt(token: string | null) {
  if (token) localStorage.setItem(JWT_KEY, token)
  else localStorage.removeItem(JWT_KEY)
}

export function getJwt() {
  return localStorage.getItem(JWT_KEY)
}

export function userFromJwt(): User | null {
  const token = getJwt()
  if (!token) return null
  try {
    const claims = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/'))) as JwtClaims
    if (claims.exp * 1000 <= Date.now()) {
      setJwt(null)
      return null
    }
    return { id: claims.sub, role: claims.role, name: claims.name, email: claims.email, phone: claims.phone }
  } catch {
    setJwt(null)
    return null
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getJwt()
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  })
  if (!response.ok) {
    if (response.status === 401) setJwt(null)
    const body = await response.json().catch(() => ({ detail: 'Something went wrong' }))
    const detail = Array.isArray(body.detail) ? body.detail.map((item: { msg?: string }) => item.msg ?? 'Invalid request').join('. ') : body.detail
    throw new Error(detail ?? 'Something went wrong')
  }
  return response.json() as Promise<T>
}

export async function apiBlob(path: string): Promise<Blob> {
  const token = getJwt()
  const response = await fetch(`${API_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
  if (!response.ok) throw new Error('Unable to download this document')
  return response.blob()
}

export async function apiUpload<T>(path: string, file: File): Promise<T> {
  const token = getJwt()
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${API_URL}${path}`, { method: 'POST', headers: token ? { Authorization: `Bearer ${token}` } : {}, body: form })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: 'Upload failed' }))
    throw new Error(body.detail ?? 'Upload failed')
  }
  return response.json() as Promise<T>
}

export function mediaUrl(path?: string) {
  if (!path) return ''
  if (path.startsWith('http')) return path
  return `${new URL(API_URL).origin}${path}`
}

export function whatsappUrl(phone: string, message: string) {
  let digits = phone.replace(/\D/g, '')
  if (digits.length === 10) digits = `91${digits}`
  return `https://wa.me/${digits}?text=${encodeURIComponent(message)}`
}

export const money = (amount: number) =>
  new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(amount)

export const indiaTime = (value: string | Date) =>
  new Intl.DateTimeFormat('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata', timeZoneName: 'short' }).format(new Date(value))

export const indiaDateTime = (value: string | Date) =>
  new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata', timeZoneName: 'short' }).format(new Date(value))

export const indiaDate = (value: string | Date) =>
  new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeZone: 'Asia/Kolkata' }).format(new Date(value))

export const indiaShortDate = (value: string | Date) =>
  new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', timeZone: 'Asia/Kolkata' }).format(new Date(value))
