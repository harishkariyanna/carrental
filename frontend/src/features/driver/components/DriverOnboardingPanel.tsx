import { type FormEvent, useState } from 'react'
import { CarFront, FileCheck2, MapPin, ShieldCheck } from 'lucide-react'
import { apiUpload } from '../../../api'

interface DriverOnboardingPanelProps {
  documentsStatus: string
  verificationStatus: string
  onSubmitted?: () => void
}

export function DriverOnboardingPanel({ documentsStatus, verificationStatus, onSubmitted }: DriverOnboardingPanelProps) {
  const [documents, setDocuments] = useState<{ license: File | null; address: File | null; vehicles: File[] }>({ license: null, address: null, vehicles: [] })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!documents.license || !documents.address || !documents.vehicles.length) return
    setBusy(true); setError('')
    try {
      await apiUpload('/driver/documents/LICENSE', documents.license)
      for (const vehicle of documents.vehicles) await apiUpload('/driver/documents/VEHICLE_PHOTO', vehicle)
      await apiUpload('/driver/documents/ADDRESS_PROOF', documents.address)
      onSubmitted?.()
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }

  return <section className="panel driver-onboarding">
    <ShieldCheck />
    <p className="eyebrow">DRIVER VERIFICATION</p>
    <h1>{documentsStatus === 'SUBMITTED' ? 'Waiting for admin approval' : 'Complete your driver application'}</h1>
    <p>{documentsStatus === 'SUBMITTED' ? 'Your documents are under review. Trip orders and assignments will unlock after approval.' : 'Upload all required documents before the RideX operations team can review your account.'}</p>
    <div className="onboarding-status"><span>Documents: {documentsStatus}</span><span>Approval: {verificationStatus}</span></div>
    {documentsStatus !== 'SUBMITTED' && <form className="driver-documents-form" onSubmit={submit}>
      <label className="file-field"><FileCheck2/><span>Driving licence</span><input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" required onChange={(event)=>setDocuments({...documents,license:event.target.files?.[0]??null})}/></label>
      <label className="file-field"><CarFront/><span>Car photos</span><input type="file" accept="image/jpeg,image/png,image/webp" multiple required onChange={(event)=>setDocuments({...documents,vehicles:Array.from(event.target.files??[])})}/></label>
      <label className="file-field"><MapPin/><span>Address proof</span><input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" required onChange={(event)=>setDocuments({...documents,address:event.target.files?.[0]??null})}/></label>
      {error&&<p className="error-text">{error}</p>}<button className="button" disabled={busy}>{busy?'Uploading...':'Submit documents'}</button>
    </form>}
  </section>
}
