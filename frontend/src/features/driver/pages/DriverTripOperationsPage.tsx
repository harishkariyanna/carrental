import { type FormEvent, useEffect, useState } from 'react'
import { CarFront, Check, Clock3, MapPin, Navigation, ReceiptIndianRupee, ShieldCheck, WalletCards, X } from 'lucide-react'
import { api, apiUpload, type Booking, money } from '../../../api'
import { RouteMap } from '../../../shared/maps/RouteMap'

interface PaymentSummary { quoted_total: number; paid_amount: number; additional_charges: number; final_total: number; amount_to_collect: number }
interface TripView { booking: Booking; driver_location?: { latitude?: number; longitude?: number }; extras: Array<{ id: string; type: string; amount: number; note: string }>; payment_summary: PaymentSummary }
interface RouteEstimate { distance_m: number; duration_s: number }
interface EndTripResponse { status: string; purpose?: string; distance_m?: number }

const statusSteps = [
  { status: 'DRIVER_ACCEPTED', label: 'Accepted' },
  { status: 'DRIVER_ON_THE_WAY', label: 'On the way' },
  { status: 'DRIVER_ARRIVED', label: 'Arrived' },
  { status: 'TRIP_STARTED', label: 'In progress' },
]

export function DriverTripOperationsPage() {
  const [trip, setTrip] = useState<TripView | null>(null)
  const [startOtp, setStartOtp] = useState('')
  const [endOtp, setEndOtp] = useState('')
  const [endOtpOpen, setEndOtpOpen] = useState(false)
  const [extra, setExtra] = useState({ type: 'TOLL', amount: 0, note: '', media_id: '' })
  const [message, setMessage] = useState('')
  const [messageTone, setMessageTone] = useState<'error' | 'success'>('success')
  const [evidence, setEvidence] = useState<File | null>(null)
  const [estimate, setEstimate] = useState<RouteEstimate | null>(null)
  const [locating, setLocating] = useState(false)
  const [completed, setCompleted] = useState(false)

  const load = async () => {
    const trips = await api<Booking[]>('/driver/trips')
    const active = trips.find((item) => ['DRIVER_ACCEPTED', 'DRIVER_ON_THE_WAY', 'DRIVER_ARRIVED', 'TRIP_STARTED'].includes(item.status))
    setTrip(active ? await api<TripView>(`/trip-operations/${active.id}`) : null)
  }

  useEffect(() => {
    let cancelled = false
    const refresh = async () => {
      const trips = await api<Booking[]>('/driver/trips')
      const active = trips.find((item) => ['DRIVER_ACCEPTED', 'DRIVER_ON_THE_WAY', 'DRIVER_ARRIVED', 'TRIP_STARTED'].includes(item.status))
      const view = active ? await api<TripView>(`/trip-operations/${active.id}`) : null
      if (!cancelled) setTrip(view)
    }
    const first = window.setTimeout(() => void refresh(), 0)
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => { cancelled = true; clearTimeout(first); clearInterval(timer) }
  }, [])

  const activeBookingId = trip && ['DRIVER_ACCEPTED', 'DRIVER_ON_THE_WAY', 'DRIVER_ARRIVED', 'TRIP_STARTED'].includes(trip.booking.status) ? trip.booking.id : null
  useEffect(() => {
    if (!activeBookingId) return
    const publishLocation = () => navigator.geolocation?.getCurrentPosition(({ coords }) => void api(`/trip-operations/${activeBookingId}/location`, { method: 'POST', body: JSON.stringify({ latitude: coords.latitude, longitude: coords.longitude, accuracy: coords.accuracy }) }))
    publishLocation()
    const timer = window.setInterval(publishLocation, 5000)
    return () => clearInterval(timer)
  }, [activeBookingId])

  const trackedBooking = trip?.booking
  const driverLatitude = trip?.driver_location?.latitude
  const driverLongitude = trip?.driver_location?.longitude
  const targetLatitude = trackedBooking?.status === 'TRIP_STARTED' ? trackedBooking.drop_latitude : trackedBooking?.pickup_latitude
  const targetLongitude = trackedBooking?.status === 'TRIP_STARTED' ? trackedBooking.drop_longitude : trackedBooking?.pickup_longitude
  useEffect(() => {
    if (driverLatitude == null || driverLongitude == null || targetLatitude == null || targetLongitude == null) return
    const params = new URLSearchParams({ pickup_lat: String(driverLatitude), pickup_lng: String(driverLongitude), drop_lat: String(targetLatitude), drop_lng: String(targetLongitude) })
    let cancelled = false
    void api<RouteEstimate>(`/maps/route?${params}`).then((value) => { if (!cancelled) setEstimate(value) }).catch(() => { if (!cancelled) setEstimate(null) })
    return () => { cancelled = true }
  }, [driverLatitude, driverLongitude, targetLatitude, targetLongitude])

  const command = async (name: string, body: Record<string, unknown> = {}) => {
    if (!trip) return false
    try {
      await api(`/trip-operations/${trip.booking.id}/${name}`, { method: 'POST', body: JSON.stringify(body) })
      setMessage('')
      await load()
      return true
    } catch (reason) {
      setMessageTone('error')
      setMessage((reason as Error).message)
      return false
    }
  }
  const startNavigation = async () => {
    if (!trip) return
    try {
      await api(`/driver/trips/${trip.booking.id}/on-the-way`, { method: 'POST', body: JSON.stringify({ action_id: `on-the-way-${crypto.randomUUID()}` }) })
      setMessageTone('success'); setMessage('Navigation started. Arrival is detected automatically within 200 metres.'); await load()
    } catch (reason) { setMessageTone('error'); setMessage((reason as Error).message) }
  }
  const addExtra = async (event: FormEvent) => {
    event.preventDefault()
    if (!trip) return
    if (extra.type === 'OTHER' && !extra.note.trim()) { setMessageTone('error'); setMessage('Add a description for the other charge.'); return }
    try {
      const media = evidence ? await apiUpload<{ id: string }>(`/trip-operations/${trip.booking.id}/evidence`, evidence) : null
      await api(`/trip-operations/${trip.booking.id}/extras`, { method: 'POST', body: JSON.stringify({ ...extra, media_id: media?.id }) })
      setExtra({ type: 'TOLL', amount: 0, note: '', media_id: '' }); setEvidence(null); setMessageTone('success'); setMessage('Charge added. You can add another toll, parking, or other expense.'); await load()
    } catch (reason) { setMessageTone('error'); setMessage((reason as Error).message) }
  }
  const sendEndRequest = async (location?: { latitude: number; longitude: number }) => {
    if (!trip) return
    try {
      const response = await api<EndTripResponse>(`/trip-operations/${trip.booking.id}/request-end`, { method: 'POST', body: JSON.stringify(location ?? {}) })
      if (response.status === 'TRIP_COMPLETED') { setCompleted(true); setMessageTone('success'); setMessage('Trip completed because you are within 200 metres of the destination.'); await load(); return }
      setEndOtp(''); setEndOtpOpen(true); setMessage('');
    } catch (reason) { setMessageTone('error'); setMessage((reason as Error).message) }
    finally { setLocating(false) }
  }
  const requestEnd = () => {
    setLocating(true)
    if (!navigator.geolocation) { void sendEndRequest(); return }
    navigator.geolocation.getCurrentPosition(({ coords }) => void sendEndRequest({ latitude: coords.latitude, longitude: coords.longitude }), () => void sendEndRequest(), { enableHighAccuracy: true, timeout: 10_000 })
  }
  const verifyEnd = async (event: FormEvent) => {
    event.preventDefault()
    if (!trip || endOtp.length !== 6) return
    try {
      await api(`/trip-operations/${trip.booking.id}/verify-end/DRIVER_END`, { method: 'POST', body: JSON.stringify({ code: endOtp }) })
      setEndOtpOpen(false); setCompleted(true); setMessageTone('success'); setMessage('Customer OTP verified. Trip completed.'); await load()
    } catch (reason) { setMessageTone('error'); setMessage((reason as Error).message) }
  }

  if (!trip) return <main className="role-page empty-role">{completed ? <Check/> : <CarFront/>}<h1>{completed ? 'Trip completed' : 'No active trip'}</h1><p>{completed ? 'The final bill is now available to the customer.' : 'Accepted trips appear here.'}</p></main>
  const booking = trip.booking
  const pickup = booking.pickup_latitude != null ? { latitude: booking.pickup_latitude, longitude: booking.pickup_longitude! } : undefined
  const drop = booking.drop_latitude != null ? { latitude: booking.drop_latitude, longitude: booking.drop_longitude! } : undefined
  const driver = trip.driver_location?.latitude != null ? { latitude: trip.driver_location.latitude, longitude: trip.driver_location.longitude! } : undefined
  const currentStep = statusSteps.findIndex((step) => step.status === booking.status)
  const estimateLabel = booking.status === 'TRIP_STARTED' ? 'Destination ETA' : 'Pickup ETA'
  const distanceLabel = estimate ? (estimate.distance_m < 1000 ? `${Math.round(estimate.distance_m)} m` : `${(estimate.distance_m / 1000).toFixed(1)} km`) : null

  return <main className="role-page">
    <header><p className="eyebrow">ACTIVE TRIP</p><h1>{booking.public_id}</h1><p>{booking.pickup} → {booking.destination}</p></header>
    <div className="live-trip-grid"><RouteMap pickup={pickup} drop={drop} driver={driver}/><aside className="panel driver-ops">
      <section className="trip-progress" aria-label="Trip progress">{statusSteps.map((step, index) => <div className={index <= currentStep ? 'complete' : ''} key={step.status}><span>{index < currentStep ? <Check/> : index + 1}</span><small>{step.label}</small></div>)}</section>
      <section className="trip-operation-summary"><div><small>CURRENT STATUS</small><strong>{booking.status.replaceAll('_', ' ')}</strong></div><div><small>{estimateLabel.toUpperCase()}</small><strong>{estimate ? `${Math.max(1, Math.ceil(estimate.duration_s / 60))} min` : 'Calculating...'}</strong>{distanceLabel && <span>{distanceLabel} remaining</span>}</div></section>
      <div className="trip-fact"><MapPin/><span>{booking.status === 'TRIP_STARTED' ? booking.destination : booking.pickup}</span></div>
      {booking.passenger_phone && <div className="contact-row"><a className="button secondary compact" href={`tel:${booking.passenger_phone}`}>Call Customer</a><a className="button secondary compact" target="_blank" rel="noreferrer" href={`https://wa.me/${booking.passenger_phone.replace(/\D/g, '')}`}>WhatsApp</a></div>}
      {booking.status === 'DRIVER_ACCEPTED' && <button className="button wide" onClick={startNavigation}><Navigation/> Start Navigation</button>}
      {booking.status === 'DRIVER_ON_THE_WAY' && <button className="button wide" onClick={() => command('arrived')}>I Have Arrived</button>}
      {booking.status === 'DRIVER_ARRIVED' && <>
        {booking.service_type === 'NORMAL' && !booking.waiting_started_at && <button className="button secondary wide" onClick={() => command('start-waiting')}><Clock3/> Start Waiting Timer</button>}
        {booking.service_type === 'NORMAL' && booking.waiting_started_at && <div className="secure-note"><Clock3/><p>Waiting started. First {booking.waiting_grace_minutes ?? 15} minutes are free, then {money(booking.waiting_rate_per_minute ?? 5)} per minute is added automatically.</p></div>}
        <div className="otp-entry"><ShieldCheck/><input inputMode="numeric" maxLength={6} placeholder="Trip Start OTP" value={startOtp} onChange={(event) => setStartOtp(event.target.value.replace(/\D/g, ''))}/><button className="button" disabled={startOtp.length !== 6} onClick={() => command('start', { code: startOtp })}>Start Trip</button></div>
      </>}
      {booking.status === 'TRIP_STARTED' && <><section className="trip-charge-section"><div className="section-heading-row"><div><small>TRIP EXPENSES</small><h3><ReceiptIndianRupee/> Additional charges</h3></div><span>{trip.extras.length} added</span></div>{trip.extras.length > 0 && <div className="charge-list">{trip.extras.map((item) => <div key={item.id}><span><strong>{item.type.replaceAll('_', ' ')}</strong><small>{item.note || 'No note'}</small></span><strong>{money(item.amount)}</strong></div>)}</div>}<form className="extra-form" onSubmit={addExtra}><div className="charge-grid"><label><span>Charge type</span><select value={extra.type} onChange={(event) => setExtra({ ...extra, type: event.target.value })}><option value="TOLL">Toll</option><option value="PARKING">Parking</option><option value="OTHER">Other charge</option></select></label><label><span>Amount</span><input type="number" min="1" placeholder="₹ 0" value={extra.amount || ''} onChange={(event) => setExtra({ ...extra, amount: Number(event.target.value) })}/></label></div><label><span>Description {extra.type === 'OTHER' ? '(required)' : '(optional)'}</span><input required={extra.type === 'OTHER'} placeholder={extra.type === 'OTHER' ? 'Describe this charge' : 'Location or reference'} value={extra.note} onChange={(event) => setExtra({ ...extra, note: event.target.value })}/></label><label className="file-field"><span>Receipt image (optional)</span><input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => setEvidence(event.target.files?.[0] ?? null)}/></label><button className="button secondary wide">Add Charge</button></form></section><button className="button wide complete-trip-button" disabled={locating} onClick={requestEnd}>{locating ? 'Checking destination...' : 'Complete Trip'}</button><small className="completion-rule">Within 200 m of the destination, the trip completes immediately. Otherwise, ask the customer for their completion OTP.</small></>}
      {message && <p className={`trip-message ${messageTone}`}>{message}</p>}
      <section className="driver-payment-summary"><h3><WalletCards/> Customer payment</h3><div><span>Ride paid online</span><strong>{money(trip.payment_summary.paid_amount)}</strong></div><div><span>Waiting, toll & parking</span><strong>{money(trip.payment_summary.additional_charges)}</strong></div><div><span>Final trip total</span><strong>{money(trip.payment_summary.final_total)}</strong></div><div className="collect-due"><span>Collect from customer</span><strong>{money(trip.payment_summary.amount_to_collect)}</strong></div></section>
    </aside></div>
    {endOtpOpen && <div className="modal-backdrop" role="presentation"><section className="completion-modal" role="dialog" aria-modal="true" aria-labelledby="completion-title"><button className="modal-close" type="button" aria-label="Close completion OTP" onClick={() => setEndOtpOpen(false)}><X/></button><div className="completion-modal-icon"><ShieldCheck/></div><p className="eyebrow">CUSTOMER VERIFICATION</p><h2 id="completion-title">Enter completion OTP</h2><p>You are outside the 200-metre destination zone. Ask the customer for the OTP shown on their Live Trip page.</p><form onSubmit={verifyEnd}><input autoFocus aria-label="Completion OTP" inputMode="numeric" maxLength={6} placeholder="6-digit OTP" value={endOtp} onChange={(event) => setEndOtp(event.target.value.replace(/\D/g, ''))}/><button className="button wide" disabled={endOtp.length !== 6}>Verify & Complete Trip</button></form>{messageTone === 'error' && message && <p className="trip-message error">{message}</p>}</section></div>}
  </main>
}
