import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CarFront, Check, Clock3, MessageCircle, Navigation, Phone, ShieldCheck, UserRound } from 'lucide-react'
import { api, type Booking, indiaTime, money, whatsappUrl } from '../../../api'
import { RouteMap } from '../../../shared/maps/RouteMap'

interface TripView {
  booking: Booking
  driver?: { id: string; name?: string; phone?: string; profile_image_id?: string }
  driver_location?: { latitude?: number; longitude?: number; last_seen?: string }
  extras: Array<{ id: string; type: string; amount: number; note: string }>
}
interface RouteEstimate { distance_m: number; duration_s: number }

const statusSteps = [
  { status: 'DRIVER_ACCEPTED', label: 'Accepted' },
  { status: 'DRIVER_ON_THE_WAY', label: 'On the way' },
  { status: 'DRIVER_ARRIVED', label: 'Arrived' },
  { status: 'TRIP_STARTED', label: 'In progress' },
  { status: 'DESTINATION_REACHED', label: 'Destination' },
  { status: 'COMPLETION_OTP_PENDING', label: 'Completion' },
]

function locationFreshness(lastSeen?: string) {
  if (!lastSeen) return 'Driver location temporarily unavailable'
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(lastSeen).getTime()) / 1000))
  if (seconds < 10) return 'Location updated just now'
  if (seconds < 60) return `Location last updated ${seconds} seconds ago`
  return `Location last updated ${Math.floor(seconds / 60)} minutes ago`
}

export function CustomerLiveTripPage() {
  const [trip, setTrip] = useState<TripView | null>(null)
  const [otp, setOtp] = useState('')
  const [otpExpiresAt, setOtpExpiresAt] = useState('')
  const [estimate, setEstimate] = useState<RouteEstimate | null>(null)

  useEffect(() => {
    let cancelled = false
    const refresh = async () => {
      const dashboard = await api<{ active_booking?: Booking }>('/customer/dashboard')
      if (!dashboard.active_booking) {
        if (!cancelled) { setTrip(null); setOtp('') }
        return
      }
      const view = await api<TripView>(`/trip-operations/${dashboard.active_booking.id}`)
      const purpose = view.booking.status === 'DRIVER_ARRIVED' ? 'START' : ['DESTINATION_REACHED', 'COMPLETION_OTP_PENDING'].includes(view.booking.status) ? 'DRIVER_END' : null
      const activeOtp = purpose ? await api<{ code: string; expires_at: string }>(`/trip-operations/${view.booking.id}/otp/${purpose}`).catch(() => null) : null
      if (!cancelled) {
        setTrip(view); setOtp(activeOtp?.code ?? ''); setOtpExpiresAt(activeOtp?.expires_at ?? '')
      }
    }
    const first = window.setTimeout(() => void refresh(), 0)
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => { cancelled = true; clearTimeout(first); clearInterval(timer) }
  }, [])

  const bookingStatus = trip?.booking.status
  const driverLatitude = trip?.driver_location?.latitude
  const driverLongitude = trip?.driver_location?.longitude
  const headingToDestination = ['TRIP_STARTED', 'DESTINATION_REACHED', 'COMPLETION_OTP_PENDING'].includes(bookingStatus ?? '')
  const targetLatitude = headingToDestination ? trip?.booking.drop_latitude : trip?.booking.pickup_latitude
  const targetLongitude = headingToDestination ? trip?.booking.drop_longitude : trip?.booking.pickup_longitude
  useEffect(() => {
    if (driverLatitude == null || driverLongitude == null || targetLatitude == null || targetLongitude == null) return
    const params = new URLSearchParams({ pickup_lat: String(driverLatitude), pickup_lng: String(driverLongitude), drop_lat: String(targetLatitude), drop_lng: String(targetLongitude) })
    let cancelled = false
    void api<RouteEstimate>(`/maps/route?${params}`).then((value) => { if (!cancelled) setEstimate(value) }).catch(() => { if (!cancelled) setEstimate(null) })
    return () => { cancelled = true }
  }, [driverLatitude, driverLongitude, targetLatitude, targetLongitude])

  if (!trip) return <main className="role-page empty-role"><CarFront/><h1>No active ride</h1><p>Your live driver map appears here once a trip begins.</p><Link className="button" to="/bookings">View Bookings</Link></main>

  const booking = trip.booking
  const pickup = booking.pickup_latitude != null ? { latitude: booking.pickup_latitude, longitude: booking.pickup_longitude!, label: booking.pickup } : undefined
  const drop = booking.drop_latitude != null ? { latitude: booking.drop_latitude, longitude: booking.drop_longitude!, label: booking.destination } : undefined
  const driver = trip.driver_location?.latitude != null ? { latitude: trip.driver_location.latitude, longitude: trip.driver_location.longitude! } : undefined
  const currentStep = statusSteps.findIndex((step) => step.status === booking.status)
  const estimateLabel = booking.status === 'TRIP_STARTED' ? 'Destination ETA' : 'Driver ETA'
  const distanceLabel = estimate ? (estimate.distance_m < 1000 ? `${Math.round(estimate.distance_m)} m away` : `${(estimate.distance_m / 1000).toFixed(1)} km away`) : ''
  const statusMessage: Record<string, string> = {
    DRIVER_ACCEPTED: 'Your driver accepted the trip and is preparing to navigate.',
    DRIVER_ON_THE_WAY: `Your driver is on the way${estimate ? ` · ${Math.max(1, Math.ceil(estimate.duration_s / 60))} min · ${distanceLabel}` : ''}.`,
    DRIVER_ARRIVED: 'Your driver has arrived within 200 metres of the pickup location.',
    TRIP_STARTED: `Trip started. Please sit back and enjoy the ride${estimate ? ` · destination ETA ${Math.max(1, Math.ceil(estimate.duration_s / 60))} min` : ''}.`,
    DESTINATION_REACHED: 'You have reached the destination. Share the completion OTP when you are ready to finish the trip.',
    COMPLETION_OTP_PENDING: 'Your driver requested trip completion. Share the OTP only when you are ready to end the ride.',
  }

  return <main className="role-page">
    <header><p className="eyebrow">LIVE TRIP</p><h1>{booking.pickup} → {booking.destination}</h1><p>Driver position refreshes every five seconds.</p></header>
    <section className="trip-progress customer-trip-progress" aria-label="Trip progress">{statusSteps.map((step, index) => <div className={index <= currentStep ? 'complete' : ''} key={step.status}><span>{index < currentStep ? <Check/> : index + 1}</span><small>{step.label}</small></div>)}</section>
    {statusMessage[booking.status] && <div className={`ride-status-callout ${booking.status === 'DRIVER_ARRIVED' ? 'arrived' : ''}`}><Navigation/><div><strong>{booking.status.replaceAll('_', ' ')}</strong><p>{statusMessage[booking.status]}</p></div>{estimate && booking.status !== 'DRIVER_ARRIVED' && <span><small>{estimateLabel}</small><strong>{Math.max(1, Math.ceil(estimate.duration_s / 60))} min</strong></span>}</div>}
    <div className="live-trip-grid">
      <RouteMap pickup={pickup} drop={drop} driver={driver}/>
      <aside className="panel">
        <span className="status-badge">{booking.status.replaceAll('_', ' ')}</span>
        <h2>Trip details</h2>
        <div className="trip-fact"><UserRound/><span>{trip.driver?.name ?? 'Driver assigned'}</span></div>
        {trip.driver?.phone && <div className="contact-row"><a className="button secondary compact" href={`tel:${trip.driver.phone}`}><Phone/> Call</a><a className="button secondary compact" target="_blank" rel="noreferrer" href={whatsappUrl(trip.driver.phone, `Hello ${trip.driver.name ?? 'Driver'}, I am your RideX customer for booking ${booking.public_id}.`)}><MessageCircle/> WhatsApp</a></div>}
        <div className="trip-fact"><Clock3/><span>{locationFreshness(trip.driver_location?.last_seen)}</span></div>
        {otp && booking.status === 'DRIVER_ARRIVED' && <div className="otp-card"><ShieldCheck/><div><small>TRIP START OTP</small><strong>{otp}</strong><p>Share this only with your assigned driver when you are ready to start.</p><span>Active{otpExpiresAt ? ` · expires ${indiaTime(otpExpiresAt)}` : ''}</span></div></div>}
        {otp && ['DESTINATION_REACHED', 'COMPLETION_OTP_PENDING'].includes(booking.status) && <div className="otp-card completion"><ShieldCheck/><div><small>TRIP COMPLETION OTP</small><strong>{otp}</strong><p>Share this only with your assigned driver when you are ready to complete the trip.</p><span>Waiting for verification{otpExpiresAt ? ` · expires ${indiaTime(otpExpiresAt)}` : ''}</span></div></div>}
        <div className="fare-total"><span>Current bill</span><strong>{money(booking.total)}</strong></div>
        {trip.extras.map((extra) => <div className="fare-line" key={extra.id}><span>{extra.type}: {extra.note}</span><strong>{money(extra.amount)}</strong></div>)}
        <Link className="button secondary wide" to="/support">Contact Support</Link>
      </aside>
    </div>
  </main>
}
