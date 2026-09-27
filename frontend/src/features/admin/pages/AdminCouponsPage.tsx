import { type FormEvent, useEffect, useState } from 'react'
import { Tag } from 'lucide-react'
import { api, indiaDate, money, type User } from '../../../api'

interface Coupon {
  id: string
  code: string
  discount_type: 'PERCENTAGE' | 'FIXED'
  value: number
  minimum_booking: number
  maximum_discount: number
  valid_from: string
  valid_to: string
  usage_limit: number
  used_count: number
  scope: 'PERSONAL' | 'PUBLIC'
  customer_id?: string
  status: 'ACTIVE' | 'INACTIVE'
}

const initialForm = () => {
  const now = new Date()
  const later = new Date(now.getTime() + 30 * 86_400_000)
  return { code: '', discount_type: 'PERCENTAGE' as 'PERCENTAGE'|'FIXED', value: 10, minimum_booking: 1000, maximum_discount: 500, valid_from: now.toISOString().slice(0, 16), valid_to: later.toISOString().slice(0, 16), usage_limit: 100, scope: 'PUBLIC' as 'PERSONAL'|'PUBLIC', customer_id: '', status: 'ACTIVE' as const }
}

export function AdminCouponsPage() {
  const [coupons, setCoupons] = useState<Coupon[]>([])
  const [customers, setCustomers] = useState<User[]>([])
  const [form, setForm] = useState(initialForm)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  useEffect(() => { void api<Coupon[]>('/admin/coupons').then(setCoupons); void api<User[]>('/admin/users').then((items) => setCustomers(items.filter((item) => item.role === 'CUSTOMER'))) }, [])
  const create = async (event: FormEvent) => {
    event.preventDefault(); setError('')
    try {
      const payload = { ...form, customer_id: form.scope === 'PERSONAL' ? form.customer_id : null, usage_limit: form.scope === 'PERSONAL' ? 1 : form.usage_limit, valid_from: new Date(form.valid_from).toISOString(), valid_to: new Date(form.valid_to).toISOString() }
      const created = await api<Coupon>('/admin/coupons', { method: 'POST', body: JSON.stringify(payload) })
      setCoupons((items) => [...items, created]); setForm(initialForm()); setMessage(`${created.code} created as a ${created.scope.toLowerCase()} one-time offer.`)
    } catch (reason) { setError((reason as Error).message) }
  }
  const toggle = async (coupon: Coupon) => {
    const updated = await api<Coupon>(`/admin/coupons/${coupon.id}`, { method: 'PATCH', body: JSON.stringify({ ...coupon, status: coupon.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE' }) })
    setCoupons((items) => items.map((item) => item.id === updated.id ? updated : item))
  }
  const customerName = (id?: string) => customers.find((customer) => customer.id === id)?.name ?? 'Selected customer'

  return <>
    <div className="page-title"><h1>Coupons</h1><p>Create one-time personal coupons or public offers usable once by each customer.</p></div>
    {message&&<div className="admin-notice">{message}</div>}{error&&<div className="error-state"><strong>Unable to create coupon</strong><p>{error}</p></div>}
    <form className="panel coupon-editor" onSubmit={create}>
      <div className="segmented coupon-scope"><button type="button" className={form.scope==='PUBLIC'?'active':''} onClick={()=>setForm({...form,scope:'PUBLIC',customer_id:''})}>Offer for everyone</button><button type="button" className={form.scope==='PERSONAL'?'active':''} onClick={()=>setForm({...form,scope:'PERSONAL',usage_limit:1})}>One customer only</button></div>
      <div className="coupon-editor-grid"><label><span>Unique coupon code</span><input value={form.code} onChange={(event)=>setForm({...form,code:event.target.value.toUpperCase()})} required/></label><label><span>Discount type</span><select value={form.discount_type} onChange={(event)=>setForm({...form,discount_type:event.target.value as 'PERCENTAGE'|'FIXED'})}><option value="PERCENTAGE">Percentage</option><option value="FIXED">Fixed amount</option></select></label><label><span>Discount value</span><input type="number" min="1" value={form.value} onChange={(event)=>setForm({...form,value:Number(event.target.value)})}/></label><label><span>Minimum ride value</span><input type="number" min="0" value={form.minimum_booking} onChange={(event)=>setForm({...form,minimum_booking:Number(event.target.value)})}/></label><label><span>Maximum discount</span><input type="number" min="0" value={form.maximum_discount} onChange={(event)=>setForm({...form,maximum_discount:Number(event.target.value)})}/></label>{form.scope==='PERSONAL'?<label><span>Customer</span><select value={form.customer_id} onChange={(event)=>setForm({...form,customer_id:event.target.value})} required><option value="">Select customer</option>{customers.map((customer)=><option key={customer.id} value={customer.id}>{customer.name} · {customer.email}</option>)}</select></label>:<label><span>Total campaign redemptions</span><input type="number" min="1" value={form.usage_limit} onChange={(event)=>setForm({...form,usage_limit:Number(event.target.value)})}/></label>}<label><span>Valid from</span><input type="datetime-local" value={form.valid_from} onChange={(event)=>setForm({...form,valid_from:event.target.value})}/></label><label><span>Valid until</span><input type="datetime-local" value={form.valid_to} onChange={(event)=>setForm({...form,valid_to:event.target.value})}/></label></div><button className="button"><Tag/> Create Coupon</button>
    </form>
    <section className="panel table-panel"><div className="panel-title"><h2>Coupon campaigns</h2><span>{coupons.length} offers</span></div><div className="table-scroll"><table><thead><tr><th>Code</th><th>Audience</th><th>Discount</th><th>Minimum</th><th>Usage</th><th>Valid until</th><th>Status</th></tr></thead><tbody>{coupons.map((coupon)=><tr key={coupon.id}><td><strong>{coupon.code}</strong></td><td><span className="status-badge">{coupon.scope??'PUBLIC'}</span><small>{coupon.scope==='PERSONAL'?customerName(coupon.customer_id):'Displayed to all customers'}</small></td><td>{coupon.discount_type==='PERCENTAGE'?`${coupon.value}%`:money(coupon.value)}<small>Max {money(coupon.maximum_discount)}</small></td><td>{money(coupon.minimum_booking)}</td><td>{coupon.used_count}/{coupon.usage_limit}</td><td>{indiaDate(coupon.valid_to)}</td><td><button className="table-action" onClick={()=>void toggle(coupon)}>{coupon.status}</button></td></tr>)}</tbody></table></div></section>
  </>
}
