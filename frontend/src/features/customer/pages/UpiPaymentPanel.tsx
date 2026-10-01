import { useEffect, useState } from 'react'
import { CheckCircle2, ExternalLink, QrCode, ShieldCheck } from 'lucide-react'
import { api, apiBlob, money, type Booking } from '../../../api'

interface RazorpayResponse {
  razorpay_payment_id: string
  razorpay_order_id: string
  razorpay_signature: string
}

interface RazorpayCheckout {
  open: () => void
  on: (event: string, callback: (response: { error: { description: string } }) => void) => void
}

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => RazorpayCheckout
  }
}

export interface PaymentOrder {
  id: string
  booking_id: string
  provider_order_id: string
  amount: number
  booking_total: number
  currency: string
  payment_type: string
  upi_id: string
  qr_url?: string
  demo: boolean
  key_id?: string
  status: string
}

const frontendDemoMode = import.meta.env.VITE_DEMO_MODE === 'true'

async function loadRazorpay() {
  if (window.Razorpay) return
  await new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = 'https://checkout.razorpay.com/v1/checkout.js'
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Unable to load Razorpay Checkout'))
    document.head.appendChild(script)
  })
}

export function UpiPaymentPanel({ payment, onConfirmed }: { payment: PaymentOrder; onConfirmed: (booking: Booking) => void }) {
  const [qrUrl, setQrUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const demo = frontendDemoMode && payment.demo
  useEffect(() => {
    if (!payment.qr_url) return
    let objectUrl = ''
    void apiBlob(payment.qr_url).then((blob) => { objectUrl = URL.createObjectURL(blob); setQrUrl(objectUrl) }).catch((reason: Error) => setError(reason.message))
    return () => { if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [payment.qr_url])
  const confirmDemo = async () => {
    setBusy(true); setError('')
    try { const booking = await api<Booking>(`/payments/${payment.id}/demo-confirm`, { method: 'POST' }); setSuccess(true); onConfirmed(booking) }
    catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }
  const waitForWebhook = async () => {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      const current = await api<{ status: string }>(`/payments/${payment.id}`)
      if (current.status === 'PAID') return api<Booking>(`/bookings/${payment.booking_id}`)
      await new Promise((resolve) => window.setTimeout(resolve, 1500))
    }
    throw new Error('Payment is still being verified. Check your booking history shortly.')
  }
  const openRazorpay = async () => {
    if (frontendDemoMode && !payment.demo) { setError('Demo UI is enabled, but the backend is not in demo mode.'); return }
    setBusy(true); setError('')
    try {
      await loadRazorpay()
      if (!window.Razorpay) throw new Error('Razorpay Checkout is unavailable')
      const checkout = new window.Razorpay({
        key: payment.key_id ?? import.meta.env.VITE_RAZORPAY_KEY_ID,
        amount: payment.amount * 100,
        currency: payment.currency,
        order_id: payment.provider_order_id,
        name: 'RideX',
        description: `${payment.payment_type.startsWith('ADVANCE') ? 'Advance' : 'Full'} booking payment`,
        config: { display: { blocks: { upi: { name: 'Pay via UPI or QR', instruments: [{ method: 'upi' }] } }, sequence: ['block.upi'], preferences: { show_default_blocks: false } } },
        handler: async (response: RazorpayResponse) => {
          try {
            const booking = await api<Booking>(`/payments/${payment.id}/verify`, { method: 'POST', body: JSON.stringify(response) }).catch((reason: Error) => reason.message.includes('captured') ? waitForWebhook() : Promise.reject(reason))
            setSuccess(true); onConfirmed(booking)
          } catch (reason) { setError((reason as Error).message) }
          finally { setBusy(false) }
        },
        modal: { ondismiss: () => setBusy(false) },
        theme: { color: '#1463df' },
      })
      checkout.on('payment.failed', (response) => { setError(response.error.description); setBusy(false) })
      checkout.open()
    } catch (reason) { setError((reason as Error).message); setBusy(false) }
  }
  const advance = payment.payment_type.startsWith('ADVANCE')
  return <section className="upi-payment-panel">
    <div>{demo&&<span className="demo-mode-badge">Demo Payment Mode</span>}<p className="eyebrow">{advance ? 'ADVANCE PAYMENT' : 'FULL PAYMENT'}</p><h2>{demo?'Scan to pay':'Pay securely'} {money(payment.amount)}</h2><p>{advance ? `${money(payment.booking_total-payment.amount)} remains payable after trip charges are finalized.` : 'This confirms the full quoted ride fare.'}</p>{demo&&<div className="upi-id"><QrCode/><span>DEMO UPI ID</span><strong>{payment.upi_id}</strong></div>}</div>
    {demo&&<div className="qr-frame">{qrUrl?<img src={qrUrl} alt={`Demo UPI QR for ${money(payment.amount)}`}/>:<span>Generating QR...</span>}</div>}
    {error&&<div className="error-state"><ShieldCheck/><div><strong>Payment error</strong><p>{error}</p></div></div>}
    {success&&<div className="secure-note"><CheckCircle2/><p>Payment Successful</p></div>}
    {demo?<button className="button wide" disabled={busy} onClick={confirmDemo}><CheckCircle2/> {busy?'Verifying demo payment...':'Simulate Successful Payment'}</button>:<button className="button wide" disabled={busy||frontendDemoMode} onClick={openRazorpay}><ExternalLink/> {busy?'Opening Razorpay...':'Continue with Razorpay UPI'}</button>}
    {!demo&&<p className="secure-note">RideX marks this payment successful only after server-side Razorpay verification or a signed webhook.</p>}
  </section>
}
