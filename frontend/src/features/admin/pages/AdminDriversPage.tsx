import { type FormEvent, useEffect, useState } from 'react'
import { CheckCircle2, FileCheck2, MapPin, Plus, Search, ShieldCheck, UserRound, X } from 'lucide-react'
import { api, mediaUrl, type User } from '../../../api'

interface DriverProfile {
  id: string
  schedule_availability?: 'AVAILABLE' | 'UNAVAILABLE'
  online_status?: 'ONLINE' | 'OFFLINE'
  verification_status?: 'PENDING' | 'VERIFIED' | 'REJECTED'
  documents_status?: string
  license_number?: string
  license_expiry?: string
  rating?: number
  assigned_vehicle_id?: string
  documents?: { LICENSE?: string; VEHICLE_PHOTO?: string[]; ADDRESS_PROOF?: string }
}

interface AdminDriver extends User {
  status: 'ACTIVE' | 'INACTIVE'
  profile?: DriverProfile
}

const emptyDriver = { name: '', email: '', phone: '', password: '', license_number: '', license_expiry: '' }

export function AdminDriversPage() {
  const [drivers, setDrivers] = useState<AdminDriver[]>([])
  const [form, setForm] = useState(emptyDriver)
  const [showForm, setShowForm] = useState(false)
  const [query, setQuery] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    void api<AdminDriver[]>('/admin/drivers').then(setDrivers).catch((reason: Error) => setError(reason.message))
  }, [])

  const create = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    try {
      const created = await api<AdminDriver>('/admin/drivers', { method: 'POST', body: JSON.stringify(form) })
      setDrivers((items) => [...items, created])
      setForm(emptyDriver)
      setShowForm(false)
      setMessage('Driver created. Document verification is still required.')
    } catch (reason) {
      setError((reason as Error).message)
    }
  }

  const update = async (driver: AdminDriver, changes: Record<string, string>) => {
    setError('')
    try {
      const updated = await api<AdminDriver>(`/admin/drivers/${driver.id}`, { method: 'PATCH', body: JSON.stringify(changes) })
      setDrivers((items) => items.map((item) => item.id === driver.id ? updated : item))
      setMessage(`${updated.name} was updated.`)
    } catch (reason) {
      setError((reason as Error).message)
    }
  }

  const visible = drivers.filter((driver) => `${driver.name} ${driver.email} ${driver.phone}`.toLowerCase().includes(query.toLowerCase()))

  return <>
    <div className="page-title admin-page-title">
      <div><h1>Drivers</h1><p>Approve drivers, review documents, and control duty eligibility.</p></div>
      <button className="button compact" onClick={() => setShowForm((value) => !value)}>{showForm ? <X/> : <Plus/>}{showForm ? 'Close' : 'Add Driver'}</button>
    </div>
    {message && <div className="admin-notice"><CheckCircle2/>{message}</div>}
    {error && <div className="error-state"><ShieldCheck/><div><strong>Driver update failed</strong><p>{error}</p></div></div>}
    {showForm && <form className="panel driver-create-form" onSubmit={create}>
      <div className="panel-title"><div><p className="eyebrow">NEW DRIVER</p><h2>Create driver account</h2></div><button className="button">Create Driver</button></div>
      <div className="vehicle-editor-grid">
        <label><span>Full name</span><input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} required/></label>
        <label><span>Email</span><input type="email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} required/></label>
        <label><span>Phone</span><input value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} required/></label>
        <label><span>Temporary password</span><input type="password" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} required/></label>
        <label><span>Licence number</span><input value={form.license_number} onChange={(event) => setForm({ ...form, license_number: event.target.value })} required/></label>
        <label><span>Licence expiry</span><input type="date" value={form.license_expiry} onChange={(event) => setForm({ ...form, license_expiry: event.target.value })} required/></label>
      </div>
    </form>}
    <div className="admin-toolbar"><label><Search/><input aria-label="Search drivers" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search drivers..."/></label></div>
    <div className="admin-driver-grid">{visible.map((driver) => {
      const profile = driver.profile
      const onDuty = profile?.schedule_availability === 'AVAILABLE'
      const documentLinks = [
        profile?.documents?.LICENSE && ['Licence', profile.documents.LICENSE],
        profile?.documents?.ADDRESS_PROOF && ['Address proof', profile.documents.ADDRESS_PROOF],
        ...(profile?.documents?.VEHICLE_PHOTO ?? []).map((id, index) => [`Vehicle ${index + 1}`, id]),
      ].filter(Boolean) as string[][]
      return <article className="panel admin-driver-card" key={driver.id}>
        <header><div className="avatar">{driver.name.slice(0, 2).toUpperCase()}</div><div><h2>{driver.name}</h2><p>{driver.email} · {driver.phone}</p></div><span className={onDuty ? 'driver-duty on' : 'driver-duty leave'}>{onDuty ? 'ON DUTY' : 'ON LEAVE'}</span></header>
        <div className="driver-card-facts">
          <span><UserRound/><small>Account</small><strong>{driver.status}</strong></span>
          <span><MapPin/><small>Live presence</small><strong>{profile?.online_status ?? 'OFFLINE'}</strong></span>
          <span><ShieldCheck/><small>Verification</small><strong>{profile?.verification_status ?? 'PENDING'}</strong></span>
          <span><FileCheck2/><small>Documents</small><strong>{profile?.documents_status ?? 'INCOMPLETE'}</strong></span>
        </div>
        <div className="driver-document-links">{documentLinks.length ? documentLinks.map(([label, id]) => <a key={id} href={mediaUrl(`/api/v1/media/${id}`)} target="_blank" rel="noreferrer">{label}</a>) : <span>No documents submitted</span>}</div>
        <div className="driver-admin-controls">
          <div className="driver-duty-admin"><span>Duty eligibility</span><strong>{onDuty ? 'On duty' : 'On leave'}</strong>{onDuty ? <button className="table-action danger" onClick={() => void update(driver, { schedule_availability: 'UNAVAILABLE' })}>Place on leave</button> : <small>Driver must start duty with live location.</small>}</div>
          <label><span>Verification</span><select value={profile?.verification_status ?? 'PENDING'} onChange={(event) => void update(driver, { verification_status: event.target.value })}><option value="PENDING">Pending</option><option value="VERIFIED">Verified</option><option value="REJECTED">Rejected</option></select></label>
          <button className="button secondary compact" onClick={() => void update(driver, { status: driver.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' })}>{driver.status === 'ACTIVE' ? 'Deactivate account' : 'Activate account'}</button>
        </div>
      </article>
    })}</div>
  </>
}
