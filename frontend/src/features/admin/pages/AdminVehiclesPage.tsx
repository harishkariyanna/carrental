import { type FormEvent, useEffect, useState } from 'react'
import { Edit3, ImageUp, Plus, Save, Trash2, X } from 'lucide-react'
import { api, apiUpload, mediaUrl, money, type User, type Vehicle } from '../../../api'

type VehicleForm = Omit<Vehicle, 'id' | 'rating' | 'amenities' | 'image'> & { image: string }

const emptyVehicle: VehicleForm = {
  name: '', registration_number: '', category: 'Sedan', seats: 4, luggage: 2, transmission: 'Automatic', fuel: 'Petrol', has_ac: true, base_rate: 1000, image: '', status: 'AVAILABLE',
  local_base_fare: 500, local_included_km: 5, local_per_km: 18, local_waiting_grace_minutes: 15, local_waiting_rate_per_minute: 5,
  outstation_one_way_base_fare: 1800, outstation_one_way_per_km: 18, outstation_one_way_included_km_per_day: 150, outstation_one_way_extra_km_rate: 18, outstation_one_way_driver_bata_per_day: 500,
  outstation_one_way_base_fare_non_ac: 1600, outstation_one_way_extra_km_rate_non_ac: 16,
  outstation_round_trip_day_rate: 3000, outstation_included_km_per_day: 250,
  outstation_extra_km_rate: 18, driver_bata_per_day: 500, outstation_round_trip_day_rate_non_ac: 2700, outstation_extra_km_rate_non_ac: 16,
}

const numericFields = new Set(['seats', 'luggage', 'base_rate', 'local_base_fare', 'local_included_km', 'local_per_km', 'local_waiting_grace_minutes', 'local_waiting_rate_per_minute', 'outstation_one_way_base_fare', 'outstation_one_way_per_km', 'outstation_one_way_included_km_per_day', 'outstation_one_way_extra_km_rate', 'outstation_one_way_driver_bata_per_day', 'outstation_one_way_base_fare_non_ac', 'outstation_one_way_extra_km_rate_non_ac', 'outstation_round_trip_day_rate', 'outstation_included_km_per_day', 'outstation_extra_km_rate', 'driver_bata_per_day', 'outstation_round_trip_day_rate_non_ac', 'outstation_extra_km_rate_non_ac'])

interface DriverWithProfile extends User { status: string; profile?: { verification_status?: string; assigned_vehicle_id?: string } }

export function AdminVehiclesPage() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [drivers, setDrivers] = useState<DriverWithProfile[]>([])
  const [form, setForm] = useState<VehicleForm>(emptyVehicle)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('ALL')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => { void api<Vehicle[]>('/admin/vehicles').then(setVehicles); void api<DriverWithProfile[]>('/admin/drivers').then(setDrivers) }, [])

  const field = (key: keyof VehicleForm, label: string, type = numericFields.has(key) ? 'number' : 'text') => <label><span>{label}</span><input type={type} min={type === 'number' ? 0 : undefined} value={String(form[key])} required onChange={(event) => setForm({ ...form, [key]: type === 'number' ? Number(event.target.value) : event.target.value })}/></label>
  const reset = () => { setForm(emptyVehicle); setEditingId(null); setImageFile(null); setShowForm(false); setError('') }
  const edit = (vehicle: Vehicle) => {
    setForm({ name: vehicle.name, registration_number: vehicle.registration_number, category: vehicle.category, seats: vehicle.seats, luggage: vehicle.luggage, transmission: vehicle.transmission, fuel: vehicle.fuel, has_ac: vehicle.has_ac, base_rate: vehicle.base_rate, image: vehicle.image, status: vehicle.status, local_base_fare: vehicle.local_base_fare, local_included_km: vehicle.local_included_km, local_per_km: vehicle.local_per_km, local_waiting_grace_minutes: vehicle.local_waiting_grace_minutes, local_waiting_rate_per_minute: vehicle.local_waiting_rate_per_minute, outstation_one_way_base_fare: vehicle.outstation_one_way_base_fare, outstation_one_way_per_km: vehicle.outstation_one_way_per_km, outstation_one_way_included_km_per_day: vehicle.outstation_one_way_included_km_per_day, outstation_one_way_extra_km_rate: vehicle.outstation_one_way_extra_km_rate, outstation_one_way_driver_bata_per_day: vehicle.outstation_one_way_driver_bata_per_day, outstation_one_way_base_fare_non_ac: vehicle.outstation_one_way_base_fare_non_ac, outstation_one_way_extra_km_rate_non_ac: vehicle.outstation_one_way_extra_km_rate_non_ac, outstation_round_trip_day_rate: vehicle.outstation_round_trip_day_rate, outstation_included_km_per_day: vehicle.outstation_included_km_per_day, outstation_extra_km_rate: vehicle.outstation_extra_km_rate, driver_bata_per_day: vehicle.driver_bata_per_day, outstation_round_trip_day_rate_non_ac: vehicle.outstation_round_trip_day_rate_non_ac, outstation_extra_km_rate_non_ac: vehicle.outstation_extra_km_rate_non_ac })
    setEditingId(vehicle.id); setImageFile(null); setShowForm(true); setError(''); window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const save = async (event: FormEvent) => {
    event.preventDefault(); setError('')
    try {
      let saved = editingId ? await api<Vehicle>(`/admin/vehicles/${editingId}`, { method: 'PATCH', body: JSON.stringify(form) }) : await api<Vehicle>('/admin/vehicles', { method: 'POST', body: JSON.stringify(form) })
      if (imageFile) {
        const media = await apiUpload<{ url: string }>(`/admin/media/VEHICLE/${saved.id}`, imageFile)
        saved = { ...saved, image: media.url }
      }
      setVehicles((items) => editingId ? items.map((item) => item.id === saved.id ? saved : item) : [...items, saved])
      setMessage(editingId ? 'Vehicle details and tariffs updated.' : 'Vehicle created with service-specific tariffs.')
      reset()
    } catch (reason) { setError((reason as Error).message) }
  }
  const remove = async (vehicle: Vehicle) => {
    if (!confirm(`Delete ${vehicle.name}? Vehicles with active bookings cannot be deleted.`)) return
    try {
      await api(`/admin/vehicles/${vehicle.id}`, { method: 'DELETE' })
      setVehicles((items) => items.filter((item) => item.id !== vehicle.id))
      setMessage(`${vehicle.name} was deleted.`)
    } catch (reason) { setError((reason as Error).message) }
  }
  const assignDriver = async (vehicle: Vehicle, driverId: string) => {
    try {
      await api(`/admin/vehicles/${vehicle.id}/assign-driver`, { method: 'POST', body: JSON.stringify({ driver_id: driverId || null }) })
      setDrivers((items) => items.map((driver) => ({ ...driver, profile: { ...driver.profile, assigned_vehicle_id: driver.id === driverId ? vehicle.id : driver.profile?.assigned_vehicle_id === vehicle.id ? undefined : driver.profile?.assigned_vehicle_id } })))
      setMessage(driverId ? `Driver assigned to ${vehicle.registration_number}.` : `Driver unassigned from ${vehicle.registration_number}.`)
    } catch (reason) { setError((reason as Error).message) }
  }

  const statuses = ['AVAILABLE', 'BOOKED', 'ON_TRIP', 'MAINTENANCE', 'INACTIVE']
  const visible = vehicles.filter((vehicle) => (filter === 'ALL' || vehicle.status === filter) && `${vehicle.name} ${vehicle.category}`.toLowerCase().includes(query.toLowerCase()))

  return <>
    <div className="page-title admin-page-title"><div><h1>Vehicles</h1><p>Edit fleet details and define vehicle-specific local and outstation tariffs.</p></div><button className="button compact" onClick={() => { if (showForm) reset(); else setShowForm(true) }}>{showForm ? <X/> : <Plus/>}{showForm ? 'Close' : 'Add Vehicle'}</button></div>
    {message && <div className="admin-notice">{message}</div>}{error && <div className="error-state"><strong>Unable to save</strong><p>{error}</p></div>}
    {showForm && <form className="panel vehicle-editor" onSubmit={save}>
      <div className="panel-title"><div><p className="eyebrow">{editingId ? 'EDIT VEHICLE' : 'NEW VEHICLE'}</p><h2>{editingId ? form.name : 'Vehicle configuration'}</h2></div><button className="button" type="submit"><Save/> Save Vehicle</button></div>
      <fieldset><legend>Vehicle details</legend><div className="vehicle-editor-grid">{field('name', 'Vehicle name')}{field('registration_number', 'Vehicle number (KA02KK6784)')}{field('category', 'Category')}{field('seats', 'Seats')}{field('luggage', 'Luggage capacity')}{field('transmission', 'Transmission')}{field('fuel', 'Fuel')}<label><span>Status</span><select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>{statuses.map((status) => <option key={status}>{status}</option>)}</select></label></div><label className="check-row"><input type="checkbox" checked={form.has_ac} onChange={(event) => setForm({ ...form, has_ac: event.target.checked })}/> Air conditioning available</label></fieldset>
      <fieldset><legend>Local pickup & drop</legend><p className="field-hint">Fixed base includes the stated kilometres. Waiting is started by the driver after arrival; charging begins after the free grace period.</p><div className="vehicle-editor-grid">{field('local_base_fare', 'Fixed base fare')}{field('local_included_km', 'Included kilometres')}{field('local_per_km', 'Rate per extra km')}{field('local_waiting_grace_minutes', 'Free waiting minutes')}{field('local_waiting_rate_per_minute', 'Waiting price per minute')}</div></fieldset>
      <fieldset><legend>Outstation one way</legend><p className="field-hint">AC and non-AC packages share the included kilometres and driver bata; package and excess rates differ.</p><div className="vehicle-editor-grid">{field('outstation_one_way_base_fare', 'AC package fare')}{field('outstation_one_way_extra_km_rate', 'AC excess rate per km')}{field('outstation_one_way_base_fare_non_ac', 'Non-AC package fare')}{field('outstation_one_way_extra_km_rate_non_ac', 'Non-AC excess rate per km')}{field('outstation_one_way_included_km_per_day', 'Included km per day')}{field('outstation_one_way_driver_bata_per_day', 'Driver bata per day')}</div></fieldset>
      <fieldset><legend>Outstation round trip</legend><p className="field-hint">AC and non-AC daily packages share the kilometre allowance and driver bata; excess rates differ.</p><div className="vehicle-editor-grid">{field('outstation_round_trip_day_rate', 'AC package per day')}{field('outstation_extra_km_rate', 'AC excess rate per km')}{field('outstation_round_trip_day_rate_non_ac', 'Non-AC package per day')}{field('outstation_extra_km_rate_non_ac', 'Non-AC excess rate per km')}{field('outstation_included_km_per_day', 'Included km per day')}{field('driver_bata_per_day', 'Driver bata per day')}</div></fieldset>
      <label className="file-drop compact-upload"><ImageUp/><span>{imageFile?.name ?? (editingId ? 'Replace vehicle photo (optional)' : 'Upload vehicle photo')}</span><input type="file" accept="image/jpeg,image/png,image/webp" required={!editingId&&!form.image} onChange={(event) => setImageFile(event.target.files?.[0] ?? null)}/></label>
    </form>}
    <div className="admin-toolbar"><label><input aria-label="Search vehicles" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search vehicles..."/></label><select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="ALL">All statuses</option>{statuses.map((status) => <option key={status}>{status}</option>)}</select></div>
    <div className="vehicle-grid admin-vehicles">{visible.map((vehicle) => { const assigned=drivers.find((driver)=>driver.profile?.assigned_vehicle_id===vehicle.id); return <article className="vehicle-card admin-vehicle" key={vehicle.id}><div className="vehicle-image"><img src={mediaUrl(vehicle.image)} alt={vehicle.name}/><span>{vehicle.status}</span></div><div className="vehicle-body"><h3>{vehicle.name}</h3><p><strong>{vehicle.registration_number}</strong> · {vehicle.category} · {vehicle.seats} seats · {vehicle.luggage} bags</p><div className="tariff-summary"><span><small>Local</small><strong>{money(vehicle.local_base_fare)} + ₹{vehicle.local_per_km}/km</strong></span><span><small>Outstation one way</small><strong>{money(vehicle.outstation_one_way_base_fare)} / {vehicle.outstation_one_way_included_km_per_day} km</strong></span><span><small>Round trip</small><strong>{money(vehicle.outstation_round_trip_day_rate)}/day</strong></span></div><label className="vehicle-driver-select"><span>Assigned driver</span><select aria-label={`Assign driver to ${vehicle.registration_number}`} value={assigned?.id??''} onChange={(event)=>void assignDriver(vehicle,event.target.value)}><option value="">Not assigned</option>{drivers.filter((driver)=>driver.status==='ACTIVE'&&driver.profile?.verification_status==='VERIFIED').map((driver)=><option key={driver.id} value={driver.id}>{driver.name}</option>)}</select></label><div className="vehicle-admin-actions"><button className="button secondary compact" onClick={() => edit(vehicle)}><Edit3/> Edit</button><button className="danger-button compact" onClick={() => void remove(vehicle)}><Trash2/> Delete</button></div></div></article> })}</div>
  </>
}
