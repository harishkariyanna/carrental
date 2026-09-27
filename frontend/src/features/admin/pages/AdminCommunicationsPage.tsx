import { useEffect, useState } from 'react'
import { api, indiaDateTime, type User } from '../../../api'

interface Notification { id: string; recipient_name?: string; recipient_email?: string; event_type: string; title: string; message: string; read: boolean; created_at?: string }
interface Ticket { id: string; message: string; status: string; requester?: User; created_at?: string }
interface EmailDelivery { id: string; event_type: string; original_recipient: string; recipient: string; recipient_domain: string; redirected: boolean; subject: string; status: string; attempts: number; last_error?: string; delivery_note?: string; created_at?: string }

export function AdminCommunicationsPage() {
  const [notifications, setNotifications] = useState<Notification[]>([])
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [deliveries, setDeliveries] = useState<EmailDelivery[]>([])
  const [message, setMessage] = useState('')
  const loadDeliveries = () => api<EmailDelivery[]>('/admin/email-deliveries').then(setDeliveries)
  useEffect(() => { void api<Notification[]>('/admin/notifications').then(setNotifications); void api<Ticket[]>('/admin/support-requests').then(setTickets); void loadDeliveries() }, [])
  const resolve = async (id: string, status: string) => {
    const updated = await api<{ id: string; status: string }>(`/admin/support-requests/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) })
    setTickets((rows) => rows.map((row) => row.id === id ? { ...row, status: updated.status } : row))
  }
  const retry = async (delivery: EmailDelivery) => {
    await api(`/admin/email-deliveries/${delivery.id}/retry`, { method: 'POST' })
    setMessage(`Retry queued for ${delivery.original_recipient}.`)
    await loadDeliveries()
  }

  return <>
    <div className="page-title"><h1>Notifications & Delivery</h1><p>In-app events, email delivery status, and customer support requests.</p></div>
    {message&&<div className="admin-notice">{message}</div>}
    <section className="panel table-panel"><div className="panel-title"><h2>Email delivery</h2><span>{deliveries.length} messages</span></div><div className="delivery-guidance">SMTP accepted means Gmail accepted the message for delivery. A later recipient-server bounce, such as Mailinator abuse filtering, is external and may still appear in the sender inbox.</div><div className="table-scroll"><table><thead><tr><th>Recipient</th><th>Event / Subject</th><th>Status</th><th>Attempts</th><th>Created</th><th>Action</th></tr></thead><tbody>{deliveries.map((delivery)=><tr key={delivery.id}><td>{delivery.original_recipient}<small>{delivery.redirected?`Development redirect → ${delivery.recipient}`:delivery.recipient}</small></td><td>{delivery.event_type}<small>{delivery.subject}</small>{delivery.last_error&&<small className="delivery-error">{delivery.last_error}</small>}</td><td><span className={`delivery-status ${delivery.status.toLowerCase()}`}>{delivery.status.replaceAll('_',' ')}</span></td><td>{delivery.attempts}</td><td>{delivery.created_at?indiaDateTime(delivery.created_at):'N/A'}</td><td>{delivery.status==='FAILED'?<button className="table-action" onClick={()=>void retry(delivery)}>Retry</button>:'—'}</td></tr>)}</tbody></table></div></section>
    <section className="panel table-panel"><div className="panel-title"><h2>Notification log</h2><span>{notifications.length} events</span></div><div className="table-scroll"><table><thead><tr><th>Recipient</th><th>Event</th><th>Message</th><th>Read</th><th>Created</th></tr></thead><tbody>{notifications.map((item)=><tr key={item.id}><td>{item.recipient_name}<small>{item.recipient_email}</small></td><td>{item.event_type}</td><td>{item.title}<small>{item.message}</small></td><td>{item.read?'Read':'Unread'}</td><td>{item.created_at?indiaDateTime(item.created_at):'N/A'}</td></tr>)}</tbody></table></div></section>
    <section className="panel table-panel"><div className="panel-title"><h2>Support requests</h2><span>{tickets.length} tickets</span></div><div className="table-scroll"><table><thead><tr><th>Customer</th><th>Message</th><th>Status</th><th>Action</th></tr></thead><tbody>{tickets.map((ticket)=><tr key={ticket.id}><td>{ticket.requester?.name}<small>{ticket.requester?.email}</small></td><td>{ticket.message}</td><td>{ticket.status}</td><td><select value={ticket.status} onChange={(event)=>void resolve(ticket.id,event.target.value)}><option>OPEN</option><option>IN_PROGRESS</option><option>RESOLVED</option></select></td></tr>)}</tbody></table></div></section>
  </>
}
