import { type FormEvent, useEffect, useState } from 'react'
import { CheckCircle2, CircleDollarSign, LogOut, Pencil, Percent, Plus, ReceiptText, ShieldCheck, Trash2, UsersRound, X } from 'lucide-react'
import { api, indiaDateTime, money, setJwt } from '../../api'

interface OwnerSettings {
  application_service_fee_percent: number
  effective_at: string
}

interface FeeRecord {
  id: string
  booking_id: string
  payment_id: string
  configured_percentage: number
  total_booking_amount: number
  calculated_service_fee: number
  amount_collected: number
  fee_status: string
  created_at: string
}

interface OwnerReport {
  total_fees_generated: number
  owner_earnings: number
  total_amount_collected: number
  successful_payments: number
  fee_records: number
  admin_count: number
}

interface AdminAccount {
  id: string
  name: string
  email: string
  phone: string
  status: 'ACTIVE'|'INACTIVE'
  created_at?: string
  updated_at?: string
}

const emptyAdminForm = { name: '', email: '', phone: '', password: '', status: 'ACTIVE' as 'ACTIVE'|'INACTIVE' }

export function SuperAdminPage() {
  const [settings, setSettings] = useState<OwnerSettings | null>(null)
  const [fees, setFees] = useState<FeeRecord[]>([])
  const [report, setReport] = useState<OwnerReport | null>(null)
  const [admins, setAdmins] = useState<AdminAccount[]>([])
  const [adminForm, setAdminForm] = useState(emptyAdminForm)
  const [editingAdminId, setEditingAdminId] = useState<string | null>(null)
  const [showAdminForm, setShowAdminForm] = useState(false)
  const [adminBusy, setAdminBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const load = () => {
    void api<OwnerSettings>('/super-admin/settings').then(setSettings).catch((reason: Error) => setError(reason.message))
    void api<FeeRecord[]>('/super-admin/fees').then(setFees).catch((reason: Error) => setError(reason.message))
    void api<OwnerReport>('/super-admin/reports').then(setReport).catch((reason: Error) => setError(reason.message))
    void api<AdminAccount[]>('/super-admin/admins').then(setAdmins).catch((reason: Error) => setError(reason.message))
  }
  const openCreateAdmin = () => { setEditingAdminId(null); setAdminForm(emptyAdminForm); setShowAdminForm(true); setError(''); setMessage('') }
  const openEditAdmin = (admin: AdminAccount) => { setEditingAdminId(admin.id); setAdminForm({ name: admin.name, email: admin.email, phone: admin.phone, password: '', status: admin.status }); setShowAdminForm(true); setError(''); setMessage('') }
  const closeAdminForm = () => { setShowAdminForm(false); setEditingAdminId(null); setAdminForm(emptyAdminForm) }
  const saveAdmin = async (event: FormEvent) => {
    event.preventDefault(); setAdminBusy(true); setError(''); setMessage('')
    try {
      const payload = editingAdminId && !adminForm.password ? { name: adminForm.name, email: adminForm.email, phone: adminForm.phone, status: adminForm.status } : adminForm
      const saved = await api<AdminAccount>(editingAdminId?`/super-admin/admins/${editingAdminId}`:'/super-admin/admins', { method: editingAdminId?'PATCH':'POST', body: JSON.stringify(payload) })
      setAdmins((items)=>editingAdminId?items.map((item)=>item.id===saved.id?saved:item):[saved,...items])
      setReport((current)=>current&&!editingAdminId?{...current,admin_count:current.admin_count+1}:current)
      setMessage(`${saved.name} ${editingAdminId?'updated':'created'} successfully.`); closeAdminForm()
    } catch (reason) { setError((reason as Error).message) }
    finally { setAdminBusy(false) }
  }
  const deleteAdmin = async (admin: AdminAccount) => {
    if (!window.confirm(`Delete Admin ${admin.name}? This immediately removes their access.`)) return
    setError(''); setMessage('')
    try {
      await api(`/super-admin/admins/${admin.id}`, { method: 'DELETE' })
      setAdmins((items)=>items.filter((item)=>item.id!==admin.id))
      setReport((current)=>current?{...current,admin_count:Math.max(0,current.admin_count-1)}:current)
      setMessage(`${admin.name} was deleted and can no longer sign in.`)
      if (editingAdminId===admin.id) closeAdminForm()
    } catch (reason) { setError((reason as Error).message) }
  }
  useEffect(load, [])
  const save = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setMessage('')
    try {
      const updated = await api<OwnerSettings>('/super-admin/settings', { method: 'PATCH', body: JSON.stringify({ application_service_fee_percent: settings?.application_service_fee_percent }) })
      setSettings(updated); setMessage(`Application service fee updated to ${updated.application_service_fee_percent}%.`)
    } catch (reason) { setError((reason as Error).message) }
  }
  const logout = () => { setJwt(null); window.location.href = '/login' }
  return <main className="owner-shell">
    <aside className="owner-sidebar"><div><ShieldCheck/><strong>RideX Owner</strong><small>Super Admin</small></div><nav><a href="#overview"><CircleDollarSign/> Overview</a><a href="#admins"><UsersRound/> Admin Accounts</a><a href="#configuration"><Percent/> Fee Configuration</a><a href="#records"><ReceiptText/> Fee Records</a></nav><button className="admin-logout owner-logout" onClick={logout}><LogOut/> Sign out</button></aside>
    <section className="owner-main">
      <header><div><p className="eyebrow">APPLICATION OWNER</p><h1>Service Fee Control</h1><p>Configure and audit the platform fee independently from rental operations.</p></div><span className="owner-status">Owner access</span></header>
      {message&&<div className="admin-notice"><CheckCircle2/> {message}</div>}{error&&<div className="error-state"><ShieldCheck/><div><strong>Unable to load owner data</strong><p>{error}</p></div></div>}
      <section id="overview" className="owner-metrics"><article><small>Owner earnings</small><strong>{money(report?.owner_earnings??0)}</strong></article><article><small>Customer payments collected</small><strong>{money(report?.total_amount_collected??0)}</strong></article><article><small>Successful payments</small><strong>{report?.successful_payments??0}</strong></article><article><small>Admin accounts</small><strong>{report?.admin_count??admins.length}</strong></article></section>
      <section id="admins" className="owner-admin-section"><div className="owner-section-heading"><div><p className="eyebrow">ACCESS CONTROL</p><h2>Admin Accounts</h2><p>Manage the operations team without exposing Super Admin controls.</p></div><button className="button compact" onClick={showAdminForm?closeAdminForm:openCreateAdmin}>{showAdminForm?<X/>:<Plus/>}{showAdminForm?'Close':'Create Admin'}</button></div>{showAdminForm&&<form className="owner-admin-form" onSubmit={saveAdmin}><label><span>Full name</span><input value={adminForm.name} onChange={(event)=>setAdminForm({...adminForm,name:event.target.value})} required minLength={2}/></label><label><span>Email</span><input type="email" value={adminForm.email} onChange={(event)=>setAdminForm({...adminForm,email:event.target.value})} required/></label><label><span>Phone</span><input value={adminForm.phone} onChange={(event)=>setAdminForm({...adminForm,phone:event.target.value})} required minLength={10}/></label><label><span>{editingAdminId?'New password (optional)':'Password'}</span><input type="password" value={adminForm.password} onChange={(event)=>setAdminForm({...adminForm,password:event.target.value})} required={!editingAdminId} minLength={8}/></label>{editingAdminId&&<label><span>Status</span><select value={adminForm.status} onChange={(event)=>setAdminForm({...adminForm,status:event.target.value as 'ACTIVE'|'INACTIVE'})}><option value="ACTIVE">Active</option><option value="INACTIVE">Inactive</option></select></label>}<button className="button" disabled={adminBusy}>{adminBusy?'Saving...':editingAdminId?'Save changes':'Create Admin'}</button></form>}<section className="panel table-panel owner-admin-table"><div className="panel-title"><h3>Normal Admins</h3><span>{admins.length} accounts</span></div><div className="table-scroll"><table><thead><tr><th>Admin</th><th>Contact</th><th>Status</th><th>Created</th><th>Actions</th></tr></thead><tbody>{admins.map((admin)=><tr key={admin.id}><td><strong>{admin.name}</strong><small>{admin.id}</small></td><td>{admin.email}<small>{admin.phone}</small></td><td><span className="status-badge">{admin.status}</span></td><td>{admin.created_at?indiaDateTime(admin.created_at):'Existing account'}</td><td><div className="owner-admin-actions"><button className="table-action" onClick={()=>openEditAdmin(admin)}><Pencil/> Edit</button><button className="table-action danger" onClick={()=>void deleteAdmin(admin)}><Trash2/> Delete</button></div></td></tr>)}</tbody></table></div></section></section>
      <section id="configuration" className="owner-configuration"><div><p className="eyebrow">CURRENT POLICY</p><h2>Application Service Fee</h2><p>Calculated automatically from the customer's total booking amount, never from the advance.</p>{settings?.effective_at&&<small>Effective {indiaDateTime(settings.effective_at)}</small>}</div><form onSubmit={save}><label><span>Service fee percentage</span><div className="percent-input"><input aria-label="Application service fee percentage" type="number" min="0" max="100" step="0.01" value={settings?.application_service_fee_percent??2} onChange={(event)=>setSettings({...settings!,application_service_fee_percent:Number(event.target.value)})}/><Percent/></div></label><button className="button" disabled={!settings}>Save percentage</button></form></section>
      <section id="records" className="panel table-panel owner-records"><div className="panel-title"><h2>Service fee ledger</h2><span>{fees.length} records</span></div><div className="table-scroll"><table><thead><tr><th>Booking</th><th>Payment</th><th>Total bill</th><th>Rate</th><th>Service fee</th><th>Customer paid</th><th>Status</th><th>Created</th></tr></thead><tbody>{fees.map((fee)=><tr key={fee.id}><td>{fee.booking_id}</td><td>{fee.payment_id}</td><td>{money(fee.total_booking_amount)}</td><td>{fee.configured_percentage}%</td><td><strong>{money(fee.calculated_service_fee)}</strong></td><td>{money(fee.amount_collected)}</td><td><span className="status-badge">{fee.fee_status}</span></td><td>{indiaDateTime(fee.created_at)}</td></tr>)}</tbody></table></div></section>
    </section>
  </main>
}