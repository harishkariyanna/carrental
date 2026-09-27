import { useEffect, useState } from 'react'
import { Database, RefreshCw, Trash2 } from 'lucide-react'
import { api } from '../../../api'

interface CollectionInfo { name: string; count: number; cleanup_enabled: boolean }
interface DatabaseRecord { record: Record<string, unknown> & { id: string }; deletable: boolean }

export function AdminDatabasePage() {
  const [collections, setCollections] = useState<CollectionInfo[]>([])
  const [selected, setSelected] = useState('')
  const [records, setRecords] = useState<DatabaseRecord[]>([])
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const loadCollections = async () => {
    const items = await api<CollectionInfo[]>('/admin/database/collections')
    setCollections(items)
    if (!selected && items.length) setSelected(items[0].name)
  }
  const loadRecords = async (collection = selected) => { if (collection) setRecords(await api<DatabaseRecord[]>(`/admin/database/${collection}?limit=100`)) }
  useEffect(() => { let cancelled=false;void api<CollectionInfo[]>('/admin/database/collections').then((items)=>{if(!cancelled){setCollections(items);setSelected((current)=>current||items[0]?.name||'')}});return()=>{cancelled=true} }, [])
  useEffect(() => { if(!selected)return;let cancelled=false;void api<DatabaseRecord[]>(`/admin/database/${selected}?limit=100`).then((items)=>{if(!cancelled)setRecords(items)});return()=>{cancelled=true} }, [selected])
  const remove = async (item: DatabaseRecord) => {
    if (!confirm(`Delete ${selected}/${item.record.id}? This cannot be undone.`)) return
    try { await api(`/admin/database/${selected}/${item.record.id}`, { method: 'DELETE' }); setRecords((rows) => rows.filter((row) => row.record.id !== item.record.id)); setMessage('Record deleted.'); await loadCollections() }
    catch (reason) { setError((reason as Error).message) }
  }
  const cleanup = async () => {
    if (!confirm(`Delete all eligible cleanup records from ${selected}? Protected and operational records remain.`)) return
    try { const result = await api<{ deleted: number }>(`/admin/database/${selected}`, { method: 'DELETE' }); setMessage(`${result.deleted} eligible records deleted.`); await loadCollections(); await loadRecords() }
    catch (reason) { setError((reason as Error).message) }
  }
  const current = collections.find((item) => item.name === selected)
  return <>
    <div className="page-title admin-page-title"><div><h1>Database</h1><p>Inspect Atlas records safely and clean only disposable data.</p></div><button className="button secondary compact" onClick={()=>{void loadCollections();void loadRecords()}}><RefreshCw/> Refresh</button></div>
    <div className="database-warning"><Database/><div><strong>Protected by design</strong><p>Passwords, OTPs, and binary blobs are redacted. Users, bookings, payments, vehicles, drivers, audit logs, and billing records cannot be deleted here.</p></div></div>
    {message&&<div className="admin-notice">{message}</div>}{error&&<div className="error-state"><strong>Database action failed</strong><p>{error}</p></div>}
    <div className="database-console"><aside className="database-collections">{collections.map((collection)=><button className={selected===collection.name?'active':''} key={collection.name} onClick={()=>{setSelected(collection.name);setError('');setMessage('')}}><span>{collection.name.replaceAll('_',' ')}</span><strong>{collection.count}</strong></button>)}</aside><section className="panel database-records"><div className="panel-title"><div><h2>{selected.replaceAll('_',' ')}</h2><span>{records.length} displayed · maximum 100</span></div>{current?.cleanup_enabled&&<button className="danger-button compact" onClick={()=>void cleanup()}><Trash2/> Clear eligible</button>}</div>{records.length?<div className="database-record-list">{records.map((item)=><article key={item.record.id}><div><strong>{item.record.id}</strong><pre>{JSON.stringify(Object.fromEntries(Object.entries(item.record).filter(([key])=>key!=='id')),null,2)}</pre></div>{item.deletable?<button className="table-action danger" onClick={()=>void remove(item)}><Trash2/> Delete</button>:<span className="protected-label">Protected</span>}</article>)}</div>:<div className="customer-empty"><Database/><h3>No records</h3><p>This collection is empty.</p></div>}</section></div>
  </>
}
