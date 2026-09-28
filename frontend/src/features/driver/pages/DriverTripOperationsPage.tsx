import { type FormEvent, useEffect, useState } from 'react'
import { CarFront, Check, Clock3, MapPin, Navigation, ReceiptIndianRupee, ShieldCheck, WalletCards } from 'lucide-react'
import { api, apiUpload, type Booking, money } from '../../../api'
import { RouteMap } from '../../../shared/maps/RouteMap'

interface PaymentSummary { quoted_total: number; paid_amount: number; driver_collected_amount: number; additional_charges: number; final_total: number; amount_to_collect: number }
interface TripView { booking: Booking; driver_location?: { latitude?: number; longitude?: number }; extras: Array<{ id: string; type: string; amount: number; note: string }>; payment_summary: PaymentSummary }
interface RouteEstimate { distance_m: number; duration_s: number }

const statusSteps = [
  { status: 'DRIVER_ACCEPTED', label: 'Accepted' },
  { status: 'DRIVER_ON_THE_WAY', label: 'On the way' },
  { status: 'DRIVER_ARRIVED', label: 'Arrived' },
  { status: 'TRIP_STARTED', label: 'In progress' },
  { status: 'DESTINATION_REACHED', label: 'Destination' },
  { status: 'COMPLETION_OTP_PENDING', label: 'Complete' },
]

const activeStatuses = ['DRIVER_ACCEPTED', 'DRIVER_ON_THE_WAY', 'DRIVER_ARRIVED', 'TRIP_STARTED', 'DESTINATION_REACHED', 'COMPLETION_OTP_PENDING']

function SwipeAction({ label, onConfirm, disabled = false }: { label: string; onConfirm: () => void; disabled?: boolean }) {
  const [value, setValue] = useState(0)
  const finish = (currentValue: number) => {
    if (currentValue >= 90 && !disabled) onConfirm()
    setValue(0)
  }
  return <label className={`swipe-action ${disabled ? 'disabled' : ''}`}><span>{label}</span><input aria-label={label} type="range" min="0" max="100" value={value} disabled={disabled} onChange={(event) => setValue(Number(event.target.value))} onPointerUp={(event) => finish(Number(event.currentTarget.value))} onKeyUp={(event) => { if (event.key === 'Enter') finish(Number(event.currentTarget.value)) }}/></label>
}

export function DriverTripOperationsPage() {
  const [trip, setTrip] = useState<TripView | null>(null)
  const [startOtp, setStartOtp] = useState('')
  const [endOtp, setEndOtp] = useState('')
  const [extra, setExtra] = useState({ type: 'TOLL', amount: 0, note: '', media_id: '' })
  const [message, setMessage] = useState('')
  const [messageTone, setMessageTone] = useState<'error' | 'success'>('success')
  const [evidence, setEvidence] = useState<File | null>(null)
  const [estimate, setEstimate] = useState<RouteEstimate | null>(null)
  const [locating, setLocating] = useState(false)
  const [completed, setCompleted] = useState(false)
  const [balanceMethod, setBalanceMethod] = useState<'CASH' | 'UPI'>('CASH')

  const load = async () => {
    const trips = await api<Booking[]>('/driver/trips')
    const active = trips.find((item) => activeStatuses.includes(item.status))
    setTrip(active ? await api<TripView>(`/trip-operations/${active.id}`) : null)
  }

  useEffect(() => {
    let cancelled = false
    const refresh = async () => {
      const trips = await api<Booking[]>('/driver/trips')
      const active = trips.find((item) => activeStatuses.includes(item.status))
      const view = active ? await api<TripView>(`/trip-operations/${active.id}`) : null
      if (!cancelled) setTrip(view)
    }
    const first = window.setTimeout(() => void refresh(), 0)
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => { cancelled = true; clearTimeout(first); clearInterval(timer) }
  }, [])

  const activeBookingId = trip && activeStatuses.includes(trip.booking.status) ? trip.booking.id : null
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
  const headingToDestination = ['TRIP_STARTED', 'DESTINATION_REACHED', 'COMPLETION_OTP_PENDING'].includes(trackedBooking?.status ?? '')
  const targetLatitude = headingToDestination ? trackedBooking?.drop_latitude : trackedBooking?.pickup_latitude
  const targetLongitude = headingToDestination ? trackedBooking?.drop_longitude : trackedBooking?.pickup_longitude
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
      const response = await api<{ status: string }>(`/trip-operations/${trip.booking.id}/request-end`, { method: 'POST', body: JSON.stringify(location ?? {}) })
      if (response.status === 'TRIP_COMPLETED') { setCompleted(true); setMessageTone('success'); setMessage('Trip completed within the destination zone.'); await load(); return }
      setEndOtp(''); setMessageTone('success'); setMessage('You are outside the 200-metre destination zone. Ask the customer for the completion OTP.'); await load()
    } catch (reason) { setMessageTone('error'); setMessage((reason as Error).message) }
    finally { setLocating(false) }
  }
  const requestEnd = () => {
    setLocating(true)
    if (!navigator.geolocation) { void sendEndRequest(); return }
    navigator.geolocation.getCurrentPosition(({ coords }) => void sendEndRequest({ latitude: coords.latitude, longitude: coords.longitude }), () => void sendEndRequest(), { enableHighAccuracy: true, timeout: 10_000 })
  }
  const recordBalanceAndFinish = async () => {
    if (!trip) return
    setLocating(true); setMessage('')
    try {
      await api(`/trip-operations/${trip.booking.id}/record-balance`, { method: 'POST', body: JSON.stringify({ method: balanceMethod }) })
      setMessageTone('success'); setMessage(`Final balance recorded by ${balanceMethod}. Checking destination...`)
      if (!navigator.geolocation) { await sendEndRequest(); return }
      navigator.geolocation.getCurrentPosition(({ coords }) => void sendEndRequest({ latitude: coords.latitude, longitude: coords.longitude }), () => void sendEndRequest(), { enableHighAccuracy: true, timeout: 10_000 })
    } catch (reason) { setLocating(false); setMessageTone('error'); setMessage((reason as Error).message) }
  }
  const verifyEnd = async (event: FormEvent) => {
    event.preventDefault()
    if (!trip || endOtp.length !== 6) return
    try {
      await api(`/trip-operations/${trip.booking.id}/verify-end/DRIVER_END`, { method: 'POST', body: JSON.stringify({ code: endOtp }) })
      setCompleted(true); setMessageTone('success'); setMessage('Customer OTP verified. Trip completed.'); await load()
    } catch (reason) { setMessageTone('error'); setMessage((reason as Error).message) }
  }

  if (!trip) return <main className="role-page empty-role">{completed ? <Check/> : <CarFront/>}<h1>{completed ? 'Trip completed' : 'No active trip'}</h1><p>{completed ? 'The final bill is now available to the customer.' : 'Accepted trips appear here.'}</p></main>
  const booking = trip.booking
  const pickup = booking.pickup_latitude != null ? { latitude: booking.pickup_latitude, longitude: booking.pickup_longitude! } : undefined
  const drop = booking.drop_latitude != null ? { latitude: booking.drop_latitude, longitude: booking.drop_longitude! } : undefined
  const driver = trip.driver_location?.latitude != null ? { latitude: trip.driver_location.latitude, longitude: trip.driver_location.longitude! } : undefined
  const currentStep = statusSteps.findIndex((step) => step.status === booking.status)
  const estimateLabel = headingToDestination ? 'Destination ETA' : 'Pickup ETA'
  const distanceLabel = estimate ? (estimate.distance_m < 1000 ? `${Math.round(estimate.distance_m)} m` : `${(estimate.distance_m / 1000).toFixed(1)} km`) : null
  const navigationUrl = targetLatitude != null && targetLongitude != null ? `https://www.google.com/maps/dir/?api=1&destination=${targetLatitude},${targetLongitude}&travelmode=driving` : ''

  return <main className="role-page">
    <header><p className="eyebrow">ACTIVE TRIP</p><h1>{booking.public_id}</h1><p>{booking.pickup} → {booking.destination}</p></header>
    <div className="live-trip-grid"><RouteMap pickup={headingToDestination ? undefined : pickup} drop={headingToDestination ? drop : undefined} driver={driver}/><aside className="panel driver-ops">
      <section className="trip-progress" aria-label="Trip progress">{statusSteps.map((step, index) => <div className={index <= currentStep ? 'complete' : ''} key={step.status}><span>{index < currentStep ? <Check/> : index + 1}</span><small>{step.label}</small></div>)}</section>
      <section className="trip-operation-summary"><div><small>CURRENT STATUS</small><strong>{booking.status.replaceAll('_', ' ')}</strong></div><div><small>{estimateLabel.toUpperCase()}</small><strong>{estimate ? `${Math.max(1, Math.ceil(estimate.duration_s / 60))} min` : 'Calculating...'}</strong>{distanceLabel && <span>{distanceLabel} remaining</span>}</div></section>
      <div className="trip-fact"><MapPin/><span>{headingToDestination ? booking.destination : booking.pickup}</span></div>
      {booking.passenger_phone && <div className="contact-row"><a className="button secondary compact" href={`tel:${booking.passenger_phone}`}>Call Customer</a><a className="button secondary compact" target="_blank" rel="noreferrer" href={`https://wa.me/${booking.passenger_phone.replace(/\D/g, '')}`}>WhatsApp</a></div>}
      {navigationUrl && !['DRIVER_ARRIVED', 'DESTINATION_REACHED', 'COMPLETION_OTP_PENDING'].includes(booking.status) && <a className="button secondary wide" href={navigationUrl} target="_blank" rel="noreferrer"><Navigation/> Open in Google Maps</a>}
      {booking.status === 'DRIVER_ACCEPTED' && <button className="button wide" onClick={startNavigation}><Navigation/> Start Navigation</button>}
      {booking.status === 'DRIVER_ON_THE_WAY' && <SwipeAction label="Swipe to confirm pickup arrival" onConfirm={() => void command('arrived')}/>}
      {booking.status === 'DRIVER_ARRIVED' && <>
        {booking.service_type === 'NORMAL' && !booking.waiting_started_at && <button className="button secondary wide" onClick={() => command('start-waiting')}><Clock3/> Start Waiting Timer</button>}
        {booking.service_type === 'NORMAL' && booking.waiting_started_at && <div className="secure-note"><Clock3/><p>Waiting started. First {booking.waiting_grace_minutes ?? 15} minutes are free, then {money(booking.waiting_rate_per_minute ?? 5)} per minute is added automatically.</p></div>}
        <div className="otp-entry"><ShieldCheck/><input inputMode="numeric" maxLength={6} placeholder="Trip Start OTP" value={startOtp} onChange={(event) => setStartOtp(event.target.value.replace(/\D/g, ''))}/><button className="button" disabled={startOtp.length !== 6} onClick={() => void command('start', { code: startOtp }).then((started) => { if (started) setStartOtp('') })}>Start Trip</button></div>
      </>}
      {booking.status === 'TRIP_STARTED' && <><section className="trip-charge-section"><div className="section-heading-row"><div><small>TRIP EXPENSES</small><h3><ReceiptIndianRupee/> Additional charges</h3></div><span>{trip.extras.length} added</span></div>{trip.extras.length > 0 && <div className="charge-list">{trip.extras.map((item) => <div key={item.id}><span><strong>{item.type.replaceAll('_', ' ')}</strong><small>{item.note || 'No note'}</small></span><strong>{money(item.amount)}</strong></div>)}</div>}<form className="extra-form" onSubmit={addExtra}><div className="charge-grid"><label><span>Charge type</span><select value={extra.type} onChange={(event) => setExtra({ ...extra, type: event.target.value })}><option value="TOLL">Toll</option><option value="PARKING">Parking</option><option value="OTHER">Other charge</option></select></label><label><span>Amount</span><input type="number" min="1" placeholder="₹ 0" value={extra.amount || ''} onChange={(event) => setExtra({ ...extra, amount: Number(event.target.value) })}/></label></div><label><span>Description {extra.type === 'OTHER' ? '(required)' : '(optional)'}</span><input required={extra.type === 'OTHER'} placeholder={extra.type === 'OTHER' ? 'Describe this charge' : 'Location or reference'} value={extra.note} onChange={(event) => setExtra({ ...extra, note: event.target.value })}/></label><label className="file-field"><span>Receipt image (optional)</span><input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => setEvidence(event.target.files?.[0] ?? null)}/></label><button className="button secondary wide">Add Charge</button></form></section>{trip.payment_summary.amount_to_collect>0?<section className="balance-collection"><div><small>FINAL BALANCE</small><strong>{money(trip.payment_summary.amount_to_collect)}</strong></div><label><span>Received by</span><select value={balanceMethod} onChange={(event)=>setBalanceMethod(event.target.value as 'CASH'|'UPI')}><option value="CASH">Cash</option><option value="UPI">UPI</option></select></label><button className="button wide" disabled={locating} onClick={()=>void recordBalanceAndFinish()}>{locating?'Recording payment...':'Payment received & finish trip'}</button></section>:<SwipeAction label={locating ? 'Checking current location...' : 'Swipe when destination is reached'} disabled={locating} onConfirm={requestEnd}/>}<small className="completion-rule">Inside 200 m the ride completes directly. Outside that zone, the customer completion OTP is required.</small></>}
      {['DESTINATION_REACHED', 'COMPLETION_OTP_PENDING'].includes(booking.status) && <form className="otp-entry completion-otp-entry" onSubmit={verifyEnd}><ShieldCheck/><input inputMode="numeric" maxLength={6} placeholder="Completion OTP" value={endOtp} onChange={(event) => setEndOtp(event.target.value.replace(/\D/g, ''))}/><button className="button" disabled={endOtp.length !== 6}>Complete Trip</button></form>}
      {message && <p className={`trip-message ${messageTone}`}>{message}</p>}
      <section className="driver-payment-summary"><h3><WalletCards/> Customer payment</h3><div><span>Paid online</span><strong>{money(trip.payment_summary.paid_amount)}</strong></div><div><span>Received by driver</span><strong>{money(trip.payment_summary.driver_collected_amount)}</strong></div><div><span>Waiting, toll & parking</span><strong>{money(trip.payment_summary.additional_charges)}</strong></div><div><span>Final trip total</span><strong>{money(trip.payment_summary.final_total)}</strong></div><div className="collect-due"><span>Still pending</span><strong>{money(trip.payment_summary.amount_to_collect)}</strong></div></section>
    </aside></div>
  </main>
}
