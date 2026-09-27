import { useEffect, useState } from 'react'
import { CheckCircle2, QrCode, ShieldCheck } from 'lucide-react'
import { api, apiBlob, money, type Booking } from '../../../api'

export interface PaymentOrder {
  id: string
  amount: number
  booking_total: number
  currency: string
  payment_type: string
  upi_id: string
  qr_url?: string
  demo: boolean
  status: string
}

export function UpiPaymentPanel({ payment, onConfirmed }: { payment: PaymentOrder; onConfirmed: (booking: Booking) => void }) {
  const [qrUrl, setQrUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!payment.qr_url) return
    let objectUrl = ''
    void apiBlob(payment.qr_url).then((blob) => { objectUrl = URL.createObjectURL(blob); setQrUrl(objectUrl) }).catch((reason: Error) => setError(reason.message))
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [payment.qr_url])
  const confirm = async () => {
    setBusy(true); setError('')
    try { onConfirmed(await api<Booking>(`/payments/${payment.id}/demo-confirm`, { method: 'POST' })) }
    catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  const advance = payment.payment_type.startsWith('ADVANCE')
  return <section className="upi-payment-panel">
    <div><p className="eyebrow">{advance ? 'ADVANCE PAYMENT' : 'FULL PAYMENT'}</p><h2>Scan to pay {money(payment.amount)}</h2><p>{advance ? `${money(payment.booking_total-payment.amount)} remains payable after trip charges are finalized.` : 'This confirms the full quoted ride fare.'}</p><div className="upi-id"><QrCode/><span>UPI ID</span><strong>{payment.upi_id}</strong></div></div>
    <div className="qr-frame">{qrUrl?<img src={qrUrl} alt={`UPI QR for ${money(payment.amount)}`}/>:<span>Generating QR...</span>}</div>
    {error&&<div className="error-state"><ShieldCheck/><div><strong>Payment error</strong><p>{error}</p></div></div>}
    {payment.demo&&<button className="button wide" disabled={busy} onClick={confirm}><CheckCircle2/> {busy?'Updating...':'I have paid (test)'}</button>}
    {!payment.demo&&<p className="secure-note">Complete the UPI payment. Confirmation will update after payment-provider verification.</p>}
  </section>
}
