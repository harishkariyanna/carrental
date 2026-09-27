import { type FormEvent, useEffect, useState } from 'react'
import { ImageUp } from 'lucide-react'
import { api, apiUpload, mediaUrl, type User, type Vehicle } from '../../../api'

export function AdminMediaPage() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [drivers, setDrivers] = useState<User[]>([])
  const [entityType, setEntityType] = useState<'VEHICLE'|'DRIVER'>('VEHICLE')
  const [entityId, setEntityId] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [message, setMessage] = useState('')
  useEffect(()=>{void api<Vehicle[]>('/admin/vehicles').then(setVehicles);void api<User[]>('/admin/drivers').then(setDrivers)},[])
  const entities = entityType === 'VEHICLE' ? vehicles : drivers
  const submit = async(event:FormEvent)=>{event.preventDefault();if(!file||!entityId)return;const media=await apiUpload<{url:string}>(`/admin/media/${entityType}/${entityId}`,file);setMessage(`Image uploaded to MongoDB: ${mediaUrl(media.url)}`);setFile(null)}
  return <section className="role-page"><header><p className="eyebrow">MEDIA LIBRARY</p><h1>Vehicle & Driver Images</h1><p>Upload validated images directly into MongoDB blob storage.</p></header><form className="panel media-upload-form" onSubmit={submit}><label><span>Entity type</span><select value={entityType} onChange={(event)=>{setEntityType(event.target.value as 'VEHICLE'|'DRIVER');setEntityId('')}}><option>VEHICLE</option><option>DRIVER</option></select></label><label><span>Select record</span><select value={entityId} onChange={(event)=>setEntityId(event.target.value)} required><option value="">Choose...</option>{entities.map((entity)=><option key={entity.id} value={entity.id}>{entity.name}</option>)}</select></label><label className="file-drop"><ImageUp/><span>{file?.name??'Choose JPEG, PNG or WebP (max 5 MB)'}</span><input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event)=>setFile(event.target.files?.[0]??null)} required/></label><button className="button">Upload Image</button></form>{message&&<div className="secure-note"><p>{message}</p></div>}<div className="secure-note"><p>Assign approved drivers to vehicles from Admin → Vehicles.</p></div></section>
}