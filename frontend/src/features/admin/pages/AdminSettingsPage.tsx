import { type FormEvent, useEffect, useState } from 'react'
import { CheckCircle2, Mail, QrCode, Save, WalletCards } from 'lucide-react'
import { api } from '../../../api'

interface PlatformSettings {
  platform_name: string
  support_email: string
  support_phone: string
  cancellation_hours: number
  cancellation_fee_percent: number
  google_review_url: string
  maintenance_mode: boolean
  upi_id: string
  standard_advance_type: 'PERCENTAGE'|'FIXED'
  standard_advance_value: number
  airport_advance_type: 'PERCENTAGE'|'FIXED'
  airport_advance_value: number
  outstation_advance_type: 'PERCENTAGE'|'FIXED'
  outstation_advance_value: number
  database: string
  email_configured: boolean
  payments_configured: boolean
}

export function AdminSettingsPage() {
  const [form, setForm] = useState<PlatformSettings | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  useEffect(() => { void api<PlatformSettings>('/admin/settings').then(setForm) }, [])
  if (!form) return <div className="skeleton-list"><div className="skeleton"/><div className="skeleton"/></div>
  const save = async (event: FormEvent) => {
    event.preventDefault(); setError('')
    try { const updated = await api<PlatformSettings>('/admin/settings', { method: 'PATCH', body: JSON.stringify(form) }); setForm({ ...form, ...updated }); setMessage('Payment and platform settings saved to Atlas.') }
    catch (reason) { setError((reason as Error).message) }
  }
  const advance = (service: 'standard'|'airport'|'outstation', label: string) => <fieldset><legend>{label} advance</legend><p className="field-hint">Choose a percentage of the discounted fare or a fixed amount to collect before confirmation.</p><div className="settings-grid"><label><span>Advance type</span><select value={form[`${service}_advance_type`]} onChange={(event)=>setForm({...form,[`${service}_advance_type`]:event.target.value})}><option value="PERCENTAGE">Percentage</option><option value="FIXED">Fixed amount</option></select></label><label><span>{form[`${service}_advance_type`]==='PERCENTAGE'?'Percentage':'Amount in INR'}</span><input type="number" min="1" max={form[`${service}_advance_type`]==='PERCENTAGE'?100:undefined} value={form[`${service}_advance_value`]} onChange={(event)=>setForm({...form,[`${service}_advance_value`]:Number(event.target.value)})}/></label></div></fieldset>
  return <>
    <div className="page-title"><h1>Settings</h1><p>Configure UPI collection, advance policies, support, and platform identity.</p></div>
    {message&&<div className="admin-notice"><CheckCircle2/> {message}</div>}{error&&<div className="error-state"><strong>Unable to save</strong><p>{error}</p></div>}
    <div className="integration-grid"><article className="panel"><strong>Database</strong><span className="online-dot">{form.database}</span></article><article className="panel"><strong>Email</strong><span className={form.email_configured?'online-dot':'config-dot'}>{form.email_configured?'Configured':'Needs configuration'}</span></article><article className="panel"><strong>UPI</strong><span className={form.payments_configured?'online-dot':'config-dot'}>{form.payments_configured?'Configured':'Needs UPI ID'}</span></article></div>
    <form className="panel settings-editor" onSubmit={save}><fieldset><legend><QrCode/> UPI collection</legend><div className="settings-grid"><label><span>UPI ID</span><input value={form.upi_id} onChange={(event)=>setForm({...form,upi_id:event.target.value})} placeholder="business@bank" required/></label></div></fieldset>{advance('standard','Local & Hourly')}{advance('airport','Airport')}{advance('outstation','Outstation')}<fieldset><legend><Mail/> Support & policy</legend><div className="settings-grid"><label><span>Platform name</span><input value={form.platform_name} onChange={(event)=>setForm({...form,platform_name:event.target.value})}/></label><label><span>Support email</span><input type="email" value={form.support_email} onChange={(event)=>setForm({...form,support_email:event.target.value})}/></label><label><span>Support phone</span><input value={form.support_phone} onChange={(event)=>setForm({...form,support_phone:event.target.value})}/></label><label><span>Cancellation hours</span><input type="number" min="0" value={form.cancellation_hours} onChange={(event)=>setForm({...form,cancellation_hours:Number(event.target.value)})}/></label><label><span>Cancellation fee %</span><input type="number" min="0" max="100" value={form.cancellation_fee_percent} onChange={(event)=>setForm({...form,cancellation_fee_percent:Number(event.target.value)})}/></label></div></fieldset><button className="button"><Save/> Save Settings</button></form>
    <div className="secure-note"><WalletCards/><p>Development payments use a one-time UPI QR and a test confirmation button. Production requires provider verification or a payment webhook before marking funds received.</p></div>
  </>
}
