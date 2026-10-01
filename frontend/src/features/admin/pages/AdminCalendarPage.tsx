import { useEffect, useState } from 'react'
import { addMonths, eachDayOfInterval, endOfMonth, endOfWeek, format, isSameDay, isSameMonth, startOfMonth, startOfWeek } from 'date-fns'
import { CalendarDays, CarFront, ChevronLeft, ChevronRight, Clock3, MapPin, UserRound, X } from 'lucide-react'
import { api, indiaDateTime, money, type Booking, type User, type Vehicle } from '../../../api'

interface CalendarBooking extends Booking {
  customer?: User
  driver?: User
  vehicle?: Vehicle
}

interface CalendarResponse {
  start: string
  end: string
  bookings: CalendarBooking[]
}

const vehicleTypeLabel = (value?: string) => ({
  SEDAN_CNG: 'Sedan with CNG',
  SEDAN_NON_CNG: 'Sedan without CNG',
  SUV: 'SUV',
  ERTIGA: 'Ertiga',
  INNOVA: 'Innova',
  INNOVA_CRYSTA: 'Innova Crysta',
  TT: 'TT',
}[value ?? ''] ?? value ?? 'Vehicle')

export function AdminCalendarPage() {
  const [month, setMonth] = useState(() => startOfMonth(new Date()))
  const [bookings, setBookings] = useState<CalendarBooking[]>([])
  const [selectedDay, setSelectedDay] = useState(() => new Date())
  const [selectedBooking, setSelectedBooking] = useState<CalendarBooking | null>(null)
  const [error, setError] = useState('')
  const rangeStart = format(startOfWeek(startOfMonth(month), { weekStartsOn: 1 }), 'yyyy-MM-dd')
  const rangeEnd = format(endOfWeek(endOfMonth(month), { weekStartsOn: 1 }), 'yyyy-MM-dd')

  useEffect(() => {
    let cancelled = false
    void api<CalendarResponse>(`/admin/bookings/calendar?start=${rangeStart}&end=${rangeEnd}`).then((result) => {
      if (!cancelled) { setBookings(result.bookings); setError('') }
    }).catch((reason: Error) => {
      if (!cancelled) setError(reason.message)
    })
    return () => { cancelled = true }
  }, [rangeEnd, rangeStart])

  const days = eachDayOfInterval({ start: new Date(`${rangeStart}T00:00:00`), end: new Date(`${rangeEnd}T00:00:00`) })
  const bookingsFor = (day: Date) => bookings.filter((booking) => isSameDay(new Date(booking.scheduled_at), day))
  const selectedBookings = bookingsFor(selectedDay)

  return <>
    <div className="page-title admin-page-title"><div><h1>Future Bookings</h1><p>See every reserved vehicle, assigned driver, and route in one calendar.</p></div><div className="calendar-month-controls"><button className="icon-button" aria-label="Previous month" onClick={() => setMonth((value) => addMonths(value, -1))}><ChevronLeft/></button><strong>{format(month, 'MMMM yyyy')}</strong><button className="icon-button" aria-label="Next month" onClick={() => setMonth((value) => addMonths(value, 1))}><ChevronRight/></button></div></div>
    {error && <div className="error-state"><CalendarDays/><div><strong>Calendar unavailable</strong><p>{error}</p></div></div>}
    <div className="admin-calendar-layout">
      <section className="panel admin-calendar">
        <div className="calendar-weekdays">{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'].map((day) => <span key={day}>{day}</span>)}</div>
        <div className="calendar-grid">{days.map((day) => { const dayBookings = bookingsFor(day); return <button type="button" key={day.toISOString()} className={`${isSameMonth(day, month) ? '' : 'outside'} ${isSameDay(day, selectedDay) ? 'selected' : ''}`} onClick={() => setSelectedDay(day)}><span className="calendar-day-number">{format(day, 'd')}</span><span className="calendar-day-count">{dayBookings.length ? `${dayBookings.length} booking${dayBookings.length === 1 ? '' : 's'}` : 'Available'}</span><span className="calendar-events">{dayBookings.slice(0, 3).map((booking) => <span key={booking.id}><i/>{format(new Date(booking.scheduled_at), 'HH:mm')} {vehicleTypeLabel(booking.vehicle?.category)}</span>)}</span></button> })}</div>
      </section>
      <aside className="panel calendar-agenda"><div className="panel-title"><div><p className="eyebrow">SELECTED DAY</p><h2>{format(selectedDay, 'EEEE, d MMMM')}</h2></div><span>{selectedBookings.length}</span></div>{selectedBookings.length ? selectedBookings.map((booking) => <button type="button" className="calendar-agenda-item" key={booking.id} onClick={() => setSelectedBooking(booking)}><span className="status-badge">{booking.status.replaceAll('_', ' ')}</span><strong>{format(new Date(booking.scheduled_at), 'hh:mm a')} · {booking.public_id}</strong><small><CarFront/> {booking.vehicle?.name ?? 'Vehicle pending'} · {booking.driver?.name ?? 'Driver pending'}</small><small><MapPin/> {booking.pickup} → {booking.destination}</small></button>) : <div className="calendar-empty"><CalendarDays/><strong>No bookings</strong><p>No vehicle or driver is reserved for this day.</p></div>}</aside>
    </div>
    {selectedBooking && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && setSelectedBooking(null)}><section className="calendar-detail-modal" role="dialog" aria-modal="true" aria-labelledby="calendar-booking-title"><button className="modal-close" aria-label="Close booking details" onClick={() => setSelectedBooking(null)}><X/></button><p className="eyebrow">FUTURE BOOKING</p><h2 id="calendar-booking-title">{selectedBooking.public_id}</h2><div className="calendar-detail-status"><span className="status-badge">{selectedBooking.status.replaceAll('_', ' ')}</span><strong>{money(selectedBooking.total)}</strong></div><div className="calendar-detail-grid"><div><Clock3/><span><small>Pickup time</small><strong>{indiaDateTime(selectedBooking.scheduled_at)}</strong></span></div><div><CarFront/><span><small>Vehicle</small><strong>{selectedBooking.vehicle?.name ?? 'Not assigned'}</strong><em>{selectedBooking.vehicle ? `${vehicleTypeLabel(selectedBooking.vehicle.category)} · ${selectedBooking.vehicle.registration_number}` : 'Assignment pending'}</em></span></div><div><UserRound/><span><small>Driver</small><strong>{selectedBooking.driver?.name ?? 'Not assigned'}</strong><em>{selectedBooking.driver?.phone ?? 'Assignment pending'}</em></span></div><div><UserRound/><span><small>Customer</small><strong>{selectedBooking.customer?.name ?? selectedBooking.passenger_name ?? 'Customer'}</strong><em>{selectedBooking.passenger_phone ?? selectedBooking.customer?.phone}</em></span></div></div><div className="calendar-route"><div><MapPin/><span><small>Pickup</small><strong>{selectedBooking.pickup}</strong></span></div><div><MapPin/><span><small>Destination</small><strong>{selectedBooking.destination}</strong></span></div></div></section></div>}
  </>
}
