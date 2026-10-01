import { type FormEvent, useEffect, useState } from 'react'
import { CheckCircle2, CircleDollarSign, ShieldCheck } from 'lucide-react'
import { api, money, type VehicleType } from '../../../api'

interface PricingRule {
  id: string
  service_type: 'AIRPORT' | 'NORMAL' | 'HOURLY' | 'OUTSTATION'
  vehicle_category: VehicleType
  base_fare: number
  per_km: number
  extra_hour: number
  driver_allowance: number
  tax_percent: number
  included_hours: number
  round_trip_multiplier: number
  status: 'DRAFT' | 'ACTIVE' | 'INACTIVE'
  version: number
}

const vehicleTypes: Array<[VehicleType, string]> = [['SEDAN_CNG','Sedan with CNG'],['SEDAN_NON_CNG','Sedan without CNG'],['ERTIGA','Ertiga'],['INNOVA','Innova'],['INNOVA_CRYSTA','Innova Crysta'],['TT','TT']]
const emptyRule = { service_type: 'NORMAL' as PricingRule['service_type'], vehicle_category: 'SEDAN_CNG' as VehicleType, base_fare: 500, per_km: 18, extra_hour: 200, driver_allowance: 0, tax_percent: 5, included_hours: 4, round_trip_multiplier: 2, status: 'DRAFT' as PricingRule['status'] }

export function AdminPricingPage() {
  const [rules,setRules]=useState<PricingRule[]>([])
  const [form,setForm]=useState(emptyRule)
  const [message,setMessage]=useState('')
  const [error,setError]=useState('')
  useEffect(()=>{void api<PricingRule[]>('/admin/pricing-rules').then(setRules).catch((reason:Error)=>setError(reason.message))},[])
  const create=async(event:FormEvent)=>{event.preventDefault();setError('');try{const created=await api<PricingRule>('/admin/pricing-rules',{method:'POST',body:JSON.stringify(form)});setRules((items)=>[...items,created]);setMessage('Pricing rule created. Activate it when ready.')}catch(reason){setError((reason as Error).message)}}
  const toggle=async(rule:PricingRule)=>{setError('');try{const updated=await api<PricingRule>(`/admin/pricing-rules/${rule.id}`,{method:'PATCH',body:JSON.stringify({...rule,status:rule.status==='ACTIVE'?'INACTIVE':'ACTIVE'})});setRules((items)=>items.map((item)=>item.id===updated.id?updated:item));setMessage(`${updated.vehicle_category} ${updated.service_type} pricing is ${updated.status.toLowerCase()}.`)}catch(reason){setError((reason as Error).message)}}
  return <><div className="page-title"><h1>Pricing</h1><p>Versioned fare rules for each supported fleet type and service.</p></div>{message&&<div className="admin-notice"><CheckCircle2/>{message}</div>}{error&&<div className="error-state"><ShieldCheck/><div><strong>Pricing update failed</strong><p>{error}</p></div></div>}<form className="panel pricing-rule-editor" onSubmit={create}><div className="panel-title"><div><p className="eyebrow">NEW FARE RULE</p><h2>Service and vehicle type</h2></div><button className="button"><CircleDollarSign/> Add Rule</button></div><div className="pricing-rule-grid"><label><span>Service</span><select value={form.service_type} onChange={(event)=>setForm({...form,service_type:event.target.value as PricingRule['service_type']})}>{['AIRPORT','NORMAL','HOURLY','OUTSTATION'].map((service)=><option key={service}>{service}</option>)}</select></label><label><span>Vehicle type</span><select value={form.vehicle_category} onChange={(event)=>setForm({...form,vehicle_category:event.target.value as VehicleType})}>{vehicleTypes.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>{(['base_fare','per_km','extra_hour','driver_allowance','tax_percent','included_hours','round_trip_multiplier'] as const).map((key)=><label key={key}><span>{key.replaceAll('_',' ')}</span><input type="number" min="0" value={form[key]} onChange={(event)=>setForm({...form,[key]:Number(event.target.value)})}/></label>)}</div></form><section className="panel table-panel"><div className="panel-title"><h2>Fare rules</h2><span>{rules.length} configured</span></div><div className="table-scroll"><table><thead><tr><th>Service</th><th>Vehicle type</th><th>Base</th><th>Per km</th><th>Extra hour</th><th>Allowance</th><th>Tax</th><th>Version</th><th>Status</th></tr></thead><tbody>{rules.map((rule)=><tr key={rule.id}><td>{rule.service_type}</td><td>{vehicleTypes.find(([value])=>value===rule.vehicle_category)?.[1]??rule.vehicle_category}</td><td>{money(rule.base_fare)}</td><td>{money(rule.per_km)}</td><td>{money(rule.extra_hour)}</td><td>{money(rule.driver_allowance)}</td><td>{rule.tax_percent}%</td><td>v{rule.version}</td><td><button className="table-action" onClick={()=>void toggle(rule)}>{rule.status}</button></td></tr>)}</tbody></table></div></section></>
}
