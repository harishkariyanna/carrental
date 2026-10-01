import { type FormEvent, useEffect, useState } from 'react'
import { CalendarDays, CarFront, Edit3, ImageUp, Plus, Save, TriangleAlert, Trash2, X } from 'lucide-react'
import { api, apiUpload, indiaDateTime, mediaUrl, money, type User, type Vehicle, type VehicleType } from '../../../api'

type VehicleForm = Omit<Vehicle, 'id' | 'rating' | 'amenities' | 'image'> & { image: string }
interface AdminVehicle extends Vehicle { future_booking_count?: number; next_booking_at?: string }
type VehicleFamily = 'SEDAN' | 'SUV' | 'TT'

const vehicleTypes: Array<{ value: VehicleType; label: string; description: string; name: string; seats: number; luggage: number; fuel: string }> = [
  { value: 'SEDAN_CNG', label: 'With CNG', description: 'Efficient four-seat city sedan', name: 'Sedan CNG', seats: 4, luggage: 2, fuel: 'CNG' },
  { value: 'SEDAN_NON_CNG', label: 'Without CNG', description: 'Petrol or diesel city sedan', name: 'Sedan', seats: 4, luggage: 2, fuel: 'Petrol' },
  { value: 'ERTIGA', label: 'Ertiga', description: 'Flexible seven-seat family car', name: 'Maruti Suzuki Ertiga', seats: 7, luggage: 3, fuel: 'Petrol' },
  { value: 'INNOVA', label: 'Innova', description: 'Spacious seven-seat MPV', name: 'Toyota Innova', seats: 7, luggage: 4, fuel: 'Diesel' },
  { value: 'INNOVA_CRYSTA', label: 'Innova Crysta', description: 'Premium seven-seat MPV', name: 'Toyota Innova Crysta', seats: 7, luggage: 4, fuel: 'Diesel' },
  { value: 'TT', label: 'TT', description: 'Tempo Traveller for groups', name: 'Force Traveller', seats: 12, luggage: 8, fuel: 'Diesel' },
]

const vehicleFamilies: Array<{ value: VehicleFamily; label: string; description: string }> = [
  { value: 'SEDAN', label: 'Sedan', description: 'Choose with or without CNG' },
  { value: 'SUV', label: 'SUV', description: 'Ertiga, Innova, or Innova Crysta' },
  { value: 'TT', label: 'TT', description: 'Tempo Traveller for larger groups' },
]

const familyForType = (type: VehicleType): VehicleFamily => type.startsWith('SEDAN') ? 'SEDAN' : type === 'TT' ? 'TT' : 'SUV'
const vehicleTypeLabel = (type: VehicleType) => type === 'SUV' ? 'SUV (choose exact model)' : vehicleTypes.find((item) => item.value === type)?.label ?? type
const familyTypes: Record<VehicleFamily, VehicleType[]> = { SEDAN: ['SEDAN_CNG', 'SEDAN_NON_CNG'], SUV: ['ERTIGA', 'INNOVA', 'INNOVA_CRYSTA'], TT: ['TT'] }

const emptyVehicle: VehicleForm = {
  name: 'Sedan CNG', registration_number: '', category: 'SEDAN_CNG', seats: 4, luggage: 2, transmission: 'Manual', fuel: 'CNG', has_ac: true, base_rate: 1000, image: '', status: 'ACTIVE',
  local_base_fare: 500, local_included_km: 5, local_per_km: 18, local_waiting_grace_minutes: 15, local_waiting_rate_per_minute: 5,
  outstation_one_way_base_fare: 1800, outstation_one_way_per_km: 18, outstation_one_way_included_km_per_day: 150, outstation_one_way_extra_km_rate: 18, outstation_one_way_driver_bata_per_day: 500,
  outstation_one_way_base_fare_non_ac: 1600, outstation_one_way_extra_km_rate_non_ac: 16,
  outstation_round_trip_day_rate: 3000, outstation_included_km_per_day: 250,
  outstation_extra_km_rate: 18, driver_bata_per_day: 500, outstation_round_trip_day_rate_non_ac: 2700, outstation_extra_km_rate_non_ac: 16,
}

const numericFields = new Set(['seats', 'luggage', 'base_rate', 'local_base_fare', 'local_included_km', 'local_per_km', 'local_waiting_grace_minutes', 'local_waiting_rate_per_minute', 'outstation_one_way_base_fare', 'outstation_one_way_per_km', 'outstation_one_way_included_km_per_day', 'outstation_one_way_extra_km_rate', 'outstation_one_way_driver_bata_per_day', 'outstation_one_way_base_fare_non_ac', 'outstation_one_way_extra_km_rate_non_ac', 'outstation_round_trip_day_rate', 'outstation_included_km_per_day', 'outstation_extra_km_rate', 'driver_bata_per_day', 'outstation_round_trip_day_rate_non_ac', 'outstation_extra_km_rate_non_ac'])

interface DriverWithProfile extends User { status: string; profile?: { verification_status?: string; assigned_vehicle_id?: string } }

export function AdminVehiclesPage() {
  const [vehicles, setVehicles] = useState<AdminVehicle[]>([])
  const [drivers, setDrivers] = useState<DriverWithProfile[]>([])
  const [form, setForm] = useState<VehicleForm>(emptyVehicle)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [vehicleFamily, setVehicleFamily] = useState<VehicleFamily>('SEDAN')
  const [inventoryFamily, setInventoryFamily] = useState<VehicleFamily>('SEDAN')
  const [inventoryVariant, setInventoryVariant] = useState<VehicleType | 'ALL'>('ALL')
  const [showLegacy, setShowLegacy] = useState(false)
  const [editorSection, setEditorSection] = useState<'DETAILS' | 'LOCAL' | 'OUTSTATION'>('DETAILS')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('ALL')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => { void api<AdminVehicle[]>('/admin/vehicles').then(setVehicles); void api<DriverWithProfile[]>('/admin/drivers').then(setDrivers) }, [])

  const field = (key: keyof VehicleForm, label: string, type = numericFields.has(key) ? 'number' : 'text') => <label><span>{label}</span><input type={type} min={type === 'number' ? 0 : undefined} value={String(form[key])} required onChange={(event) => setForm({ ...form, [key]: type === 'number' ? Number(event.target.value) : event.target.value })}/></label>
  const reset = () => { setForm(emptyVehicle); setEditingId(null); setImageFile(null); setShowForm(false); setVehicleFamily('SEDAN'); setEditorSection('DETAILS'); setError('') }
  const chooseType = (type: VehicleType) => { const preset = vehicleTypes.find((item) => item.value === type)!; setForm({ ...form, category: type, name: preset.name, seats: preset.seats, luggage: preset.luggage, fuel: preset.fuel }) }
  const chooseFamily = (family: VehicleFamily) => {
    setVehicleFamily(family)
    if (family === 'SEDAN') chooseType('SEDAN_CNG')
    if (family === 'SUV') chooseType('ERTIGA')
    if (family === 'TT') chooseType('TT')
  }
  const edit = (vehicle: Vehicle) => {
    setForm({ name: vehicle.name, registration_number: vehicle.registration_number, category: vehicle.category, seats: vehicle.seats, luggage: vehicle.luggage, transmission: vehicle.transmission, fuel: vehicle.fuel, has_ac: vehicle.has_ac, base_rate: vehicle.base_rate, image: vehicle.image, status: vehicle.status, local_base_fare: vehicle.local_base_fare, local_included_km: vehicle.local_included_km, local_per_km: vehicle.local_per_km, local_waiting_grace_minutes: vehicle.local_waiting_grace_minutes, local_waiting_rate_per_minute: vehicle.local_waiting_rate_per_minute, outstation_one_way_base_fare: vehicle.outstation_one_way_base_fare, outstation_one_way_per_km: vehicle.outstation_one_way_per_km, outstation_one_way_included_km_per_day: vehicle.outstation_one_way_included_km_per_day, outstation_one_way_extra_km_rate: vehicle.outstation_one_way_extra_km_rate, outstation_one_way_driver_bata_per_day: vehicle.outstation_one_way_driver_bata_per_day, outstation_one_way_base_fare_non_ac: vehicle.outstation_one_way_base_fare_non_ac, outstation_one_way_extra_km_rate_non_ac: vehicle.outstation_one_way_extra_km_rate_non_ac, outstation_round_trip_day_rate: vehicle.outstation_round_trip_day_rate, outstation_included_km_per_day: vehicle.outstation_included_km_per_day, outstation_extra_km_rate: vehicle.outstation_extra_km_rate, driver_bata_per_day: vehicle.driver_bata_per_day, outstation_round_trip_day_rate_non_ac: vehicle.outstation_round_trip_day_rate_non_ac, outstation_extra_km_rate_non_ac: vehicle.outstation_extra_km_rate_non_ac })
    setEditingId(vehicle.id); setImageFile(null); setShowForm(true); setVehicleFamily(familyForType(vehicle.category)); setEditorSection('DETAILS'); setError(''); window.scrollTo({ top: 0, behavior: 'smooth' })
  }
  const save = async (event: FormEvent) => {
    event.preventDefault(); setError('')
    if (form.category === 'SUV') { setEditorSection('DETAILS'); setError('Choose the exact SUV model: Ertiga, Innova, or Innova Crysta.'); return }
    try {
      let saved = editingId ? await api<Vehicle>(`/admin/vehicles/${editingId}`, { method: 'PATCH', body: JSON.stringify(form) }) : await api<Vehicle>('/admin/vehicles', { method: 'POST', body: JSON.stringify(form) })
      if (imageFile) {
        const media = await apiUpload<{ url: string }>(`/admin/media/VEHICLE/${saved.id}`, imageFile)
        saved = { ...saved, image: media.url }
      }
      setVehicles((items) => editingId ? items.map((item) => item.id === saved.id ? { ...item, ...saved } : item) : [...items, saved])
      setMessage(editingId ? 'Vehicle details and tariffs updated.' : 'Vehicle created with service-specific tariffs.')
      reset()
    } catch (reason) { setError((reason as Error).message) }
  }
  const remove = async (vehicle: Vehicle) => {
    if (!confirm(`Delete ${vehicle.name}? Vehicles with active bookings cannot be deleted.`)) return
    try {
      await api(`/admin/vehicles/${vehicle.id}`, { method: 'DELETE' })
      setVehicles((items) => items.filter((item) => item.id !== vehicle.id))
      setMessage(`${vehicle.name} was archived.`)
    } catch (reason) { setError((reason as Error).message) }
  }
  const assignDriver = async (vehicle: Vehicle, driverId: string) => {
    try {
      await api(`/admin/vehicles/${vehicle.id}/assign-driver`, { method: 'POST', body: JSON.stringify({ driver_id: driverId || null }) })
      setDrivers((items) => items.map((driver) => ({ ...driver, profile: { ...driver.profile, assigned_vehicle_id: driver.id === driverId ? vehicle.id : driver.profile?.assigned_vehicle_id === vehicle.id ? undefined : driver.profile?.assigned_vehicle_id } })))
      setMessage(driverId ? `Driver assigned to ${vehicle.registration_number}.` : `Driver unassigned from ${vehicle.registration_number}.`)
    } catch (reason) { setError((reason as Error).message) }
  }

  const statuses: Vehicle['status'][] = ['ACTIVE', 'MAINTENANCE', 'INACTIVE']
  const supportedVehicles = vehicles.filter((vehicle) => vehicle.category !== 'SUV')
  const legacyVehicles = vehicles.filter((vehicle) => vehicle.category === 'SUV')
  const selectedFamilyTypes = familyTypes[inventoryFamily]
  const visible = supportedVehicles.filter((vehicle) => selectedFamilyTypes.includes(vehicle.category) && (inventoryVariant === 'ALL' || vehicle.category === inventoryVariant) && (filter === 'ALL' || vehicle.status === filter) && `${vehicle.name} ${vehicleTypeLabel(vehicle.category)} ${vehicle.registration_number}`.toLowerCase().includes(query.toLowerCase()))
  const selectInventoryFamily = (family: VehicleFamily) => { setInventoryFamily(family); setInventoryVariant('ALL') }

  return <>
    <div className="page-title admin-page-title"><div><h1>Fleet</h1><p>Add each physical vehicle, control its tariffs, and review future booking demand.</p></div><button className="button compact" onClick={() => { if (showForm) reset(); else setShowForm(true) }}>{showForm ? <X/> : <Plus/>}{showForm ? 'Close' : 'Add Vehicle'}</button></div>
    {message && <div className="admin-notice">{message}</div>}{error && <div className="error-state"><strong>Unable to save</strong><p>{error}</p></div>}
    {showForm && <form className="panel vehicle-editor" onSubmit={save}>
      <div className="panel-title"><div><p className="eyebrow">{editingId ? 'EDIT FLEET UNIT' : 'ADD FLEET UNIT'}</p><h2>{editingId ? form.name : 'Configure a physical vehicle'}</h2></div><button className="button" type="submit"><Save/> Save Vehicle</button></div>
      <fieldset className="vehicle-classification"><legend>Vehicle category</legend><p className="field-hint">Choose the main category first, then select its fuel option or exact model.</p><div className="vehicle-family-picker">{vehicleFamilies.map((item)=><button type="button" key={item.value} className={vehicleFamily===item.value?'active':''} onClick={()=>chooseFamily(item.value)}><CarFront/><span><strong>{item.label}</strong><small>{item.description}</small></span></button>)}</div>{vehicleFamily==='SEDAN'&&<div className="vehicle-variant-section"><div><span>SEDAN OPTION</span><strong>Choose the fuel setup</strong></div><div className="vehicle-variant-picker">{vehicleTypes.filter((item)=>item.value.startsWith('SEDAN')).map((item)=><button type="button" key={item.value} className={form.category===item.value?'active':''} onClick={()=>chooseType(item.value)}><strong>{item.label}</strong><small>{item.description}</small></button>)}</div></div>}{vehicleFamily==='SUV'&&<div className="vehicle-variant-section"><div><span>SUV MODEL</span><strong>Choose the exact vehicle</strong></div><div className="vehicle-variant-picker suv-models">{vehicleTypes.filter((item)=>['ERTIGA','INNOVA','INNOVA_CRYSTA'].includes(item.value)).map((item)=><button type="button" key={item.value} className={form.category===item.value?'active':''} onClick={()=>chooseType(item.value)}><strong>{item.label}</strong><small>{item.description}</small></button>)}</div>{form.category==='SUV'&&<p className="vehicle-legacy-note">This is a legacy generic SUV. Select its exact model before saving.</p>}</div>}{vehicleFamily==='TT'&&<div className="vehicle-variant-section single"><div><span>SELECTED TYPE</span><strong>Tempo Traveller</strong><small>Capacity and vehicle name can be adjusted below.</small></div></div>}</fieldset>
      <div className="vehicle-editor-tabs"><button type="button" className={editorSection==='DETAILS'?'active':''} onClick={()=>setEditorSection('DETAILS')}>Vehicle Details</button><button type="button" className={editorSection==='LOCAL'?'active':''} onClick={()=>setEditorSection('LOCAL')}>Local Tariff</button><button type="button" className={editorSection==='OUTSTATION'?'active':''} onClick={()=>setEditorSection('OUTSTATION')}>Outstation Tariffs</button></div>
      {editorSection==='DETAILS'&&<fieldset><legend>Identity & capacity</legend><div className="vehicle-editor-grid">{field('name', 'Display name')}{field('registration_number', 'Registration number (KA02KK6784)')}{field('seats', 'Seats')}{field('luggage', 'Luggage capacity')}{field('base_rate', 'Starting base rate')}<label><span>Transmission</span><select value={form.transmission} onChange={(event)=>setForm({...form,transmission:event.target.value})}><option>Manual</option><option>Automatic</option></select></label><label><span>Fuel</span><select value={form.fuel} onChange={(event)=>setForm({...form,fuel:event.target.value})}><option>CNG</option><option>Petrol</option><option>Diesel</option><option>Electric</option></select></label><label><span>Operational status</span><select value={form.status} onChange={(event)=>setForm({...form,status:event.target.value as Vehicle['status']})}>{statuses.map((status)=><option key={status}>{status}</option>)}</select></label></div><label className="check-row"><input type="checkbox" checked={form.has_ac} onChange={(event)=>setForm({...form,has_ac:event.target.checked})}/> Air conditioning available</label><label className="file-drop compact-upload"><ImageUp/><span>{imageFile?.name??(editingId?'Replace vehicle photo (optional)':'Upload vehicle photo')}</span><input type="file" accept="image/jpeg,image/png,image/webp" required={!editingId&&!form.image} onChange={(event)=>setImageFile(event.target.files?.[0]??null)}/></label></fieldset>}
      {editorSection==='LOCAL'&&<fieldset><legend>Local pickup & drop</legend><p className="field-hint">The base fare includes the stated kilometres. Booking reservations determine availability automatically.</p><div className="vehicle-editor-grid">{field('local_base_fare','Fixed base fare')}{field('local_included_km','Included kilometres')}{field('local_per_km','Rate per extra km')}{field('local_waiting_grace_minutes','Free waiting minutes')}{field('local_waiting_rate_per_minute','Waiting price per minute')}</div></fieldset>}
      {editorSection==='OUTSTATION'&&<div className="vehicle-outstation-editor"><fieldset><legend>One way</legend><p className="field-hint">AC and non-AC package rates for a one-way outstation booking.</p><div className="vehicle-editor-grid">{field('outstation_one_way_base_fare','AC package fare')}{field('outstation_one_way_extra_km_rate','AC excess per km')}{field('outstation_one_way_base_fare_non_ac','Non-AC package fare')}{field('outstation_one_way_extra_km_rate_non_ac','Non-AC excess per km')}{field('outstation_one_way_included_km_per_day','Included km per day')}{field('outstation_one_way_driver_bata_per_day','Driver bata per day')}</div></fieldset><fieldset><legend>Round trip</legend><p className="field-hint">Daily packages, kilometre allowance, excess rates, and driver bata.</p><div className="vehicle-editor-grid">{field('outstation_round_trip_day_rate','AC package per day')}{field('outstation_extra_km_rate','AC excess per km')}{field('outstation_round_trip_day_rate_non_ac','Non-AC package per day')}{field('outstation_extra_km_rate_non_ac','Non-AC excess per km')}{field('outstation_included_km_per_day','Included km per day')}{field('driver_bata_per_day','Driver bata per day')}</div></fieldset></div>}
    </form>}
    <section className="panel fleet-catalog-nav"><div className="panel-title"><div><p className="eyebrow">FLEET CATEGORIES</p><h2>Choose a vehicle category</h2></div><span>{supportedVehicles.length} classified vehicles</span></div><div className="vehicle-family-picker fleet-family-nav">{vehicleFamilies.map((item)=>{const count=supportedVehicles.filter((vehicle)=>familyTypes[item.value].includes(vehicle.category)).length;return <button type="button" key={item.value} className={inventoryFamily===item.value?'active':''} onClick={()=>selectInventoryFamily(item.value)}><CarFront/><span><strong>{item.label}</strong><small>{item.description}</small><em>{count} vehicles</em></span></button>})}</div><div className="fleet-variant-tabs"><button type="button" className={inventoryVariant==='ALL'?'active':''} onClick={()=>setInventoryVariant('ALL')}>All {inventoryFamily}</button>{selectedFamilyTypes.map((type)=><button type="button" key={type} className={inventoryVariant===type?'active':''} onClick={()=>setInventoryVariant(type)}>{vehicleTypeLabel(type)} <span>{supportedVehicles.filter((vehicle)=>vehicle.category===type).length}</span></button>)}</div></section>
    {legacyVehicles.length>0&&<section className="legacy-fleet-queue"><div><TriangleAlert/><span><strong>{legacyVehicles.length} old SUV record{legacyVehicles.length===1?'':'s'} hidden from the fleet</strong><small>Assign each one to Ertiga, Innova, or Innova Crysta before it can be offered to customers.</small></span></div><button type="button" className="table-action" onClick={()=>setShowLegacy((value)=>!value)}>{showLegacy?'Hide records':'Review records'}</button>{showLegacy&&<div className="legacy-fleet-list">{legacyVehicles.map((vehicle)=><article key={vehicle.id}><span><strong>{vehicle.name}</strong><small>{vehicle.registration_number} · {vehicle.fuel} · {vehicle.seats} seats</small></span><button type="button" className="button secondary compact" onClick={()=>edit(vehicle)}><Edit3/> Classify</button></article>)}</div>}</section>}
    <div className="admin-toolbar"><label><input aria-label="Search vehicles" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${inventoryFamily.toLowerCase()} vehicles...`}/></label><select value={filter} onChange={(event) => setFilter(event.target.value)}><option value="ALL">All statuses</option>{statuses.map((status) => <option key={status}>{status}</option>)}</select></div>
    <div className="fleet-result-title"><div><p className="eyebrow">{inventoryFamily} INVENTORY</p><h2>{inventoryVariant==='ALL'?vehicleFamilies.find((item)=>item.value===inventoryFamily)?.label:vehicleTypeLabel(inventoryVariant)}</h2></div><span>{visible.length} physical vehicle{visible.length===1?'':'s'}</span></div>
    {visible.length?<div className="vehicle-grid admin-vehicles">{visible.map((vehicle) => { const assigned=drivers.find((driver)=>driver.profile?.assigned_vehicle_id===vehicle.id); return <article className="vehicle-card admin-vehicle" key={vehicle.id}><div className="vehicle-image"><img src={mediaUrl(vehicle.image)} alt={vehicle.name}/><span>{vehicle.status}</span></div><div className="vehicle-body"><div className="admin-vehicle-title"><div><p>{vehicleTypeLabel(vehicle.category)}</p><h3>{vehicle.name}</h3></div><strong>{vehicle.registration_number}</strong></div><p>{vehicle.seats} seats · {vehicle.luggage} bags · {vehicle.fuel} · {vehicle.transmission}</p><div className="vehicle-booking-demand"><CalendarDays/><span><strong>{vehicle.future_booking_count??0} future bookings</strong><small>{vehicle.next_booking_at?`Next: ${indiaDateTime(vehicle.next_booking_at)}`:'No upcoming reservations'}</small></span></div><div className="tariff-summary"><span><small>Local</small><strong>{money(vehicle.local_base_fare)} + ₹{vehicle.local_per_km}/km</strong></span><span><small>One way</small><strong>{money(vehicle.outstation_one_way_base_fare)}</strong></span><span><small>Round trip</small><strong>{money(vehicle.outstation_round_trip_day_rate)}/day</strong></span></div><label className="vehicle-driver-select"><span>Default driver</span><select aria-label={`Assign driver to ${vehicle.registration_number}`} value={assigned?.id??''} onChange={(event)=>void assignDriver(vehicle,event.target.value)}><option value="">Not assigned</option>{drivers.filter((driver)=>driver.status==='ACTIVE'&&driver.profile?.verification_status==='VERIFIED').map((driver)=><option key={driver.id} value={driver.id}>{driver.name}</option>)}</select></label><div className="vehicle-admin-actions"><button className="button secondary compact" onClick={()=>edit(vehicle)}><Edit3/> Edit</button><button className="danger-button compact" onClick={()=>void remove(vehicle)}><Trash2/> Archive</button></div></div></article> })}</div>:<div className="fleet-empty"><CarFront/><h3>No {inventoryFamily.toLowerCase()} vehicles yet</h3><p>Add a physical vehicle in this category to make it available for future bookings.</p><button className="button compact" onClick={()=>{setShowForm(true);chooseFamily(inventoryFamily);window.scrollTo({top:0,behavior:'smooth'})}}><Plus/> Add {inventoryFamily}</button></div>}
  </>
}
