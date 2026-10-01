import { type FormEvent, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, CarFront, FileCheck2, MapPin, ShieldCheck, UserRound, X } from 'lucide-react'
import { api, apiUpload, setJwt, type Role, type User, userFromJwt } from '../../api'

interface LoginModalProps {
  open: boolean
  initialMode?: 'login' | 'register'
  onClose: () => void
  onAuthenticated: (user: User) => void
}

export function LoginModal({ open, initialMode = 'login', onClose, onAuthenticated }: LoginModalProps) {
  const [mode, setMode] = useState(initialMode)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [registration, setRegistration] = useState({ name: '', email: '', phone: '', password: '', role: 'CUSTOMER' as Exclude<Role, 'ADMIN' | 'SUPER_ADMIN'>, license_number: '', license_expiry: '' })
  const [registeredDriver, setRegisteredDriver] = useState<User | null>(null)
  const [documents, setDocuments] = useState<{ license: File | null; address: File | null; vehicles: File[] }>({ license: null, address: null, vehicles: [] })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (!open) return null

  const login = async (event: FormEvent) => {
    event.preventDefault()
    setError(''); setBusy(true)
    try {
      const result = await api<{ access_token: string }>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
      setJwt(result.access_token)
      const user = userFromJwt()
      if (!user) throw new Error('The login token was invalid')
      onAuthenticated(user)
    } catch (reason) {
      setError((reason as Error).message)
    } finally { setBusy(false) }
  }

  const register = async (event: FormEvent) => {
    event.preventDefault(); setError(''); setBusy(true)
    try {
      const payload = registration.role === 'DRIVER' ? registration : { name: registration.name, email: registration.email, phone: registration.phone, password: registration.password, role: registration.role }
      const result = await api<{ access_token: string }>('/auth/register', { method: 'POST', body: JSON.stringify(payload) })
      setJwt(result.access_token)
      const user = userFromJwt()
      if (!user) throw new Error('The registration token was invalid')
      if (user.role === 'DRIVER') setRegisteredDriver(user)
      else onAuthenticated(user)
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }

  const uploadDocuments = async (event: FormEvent) => {
    event.preventDefault()
    if (!registeredDriver || !documents.license || !documents.address || !documents.vehicles.length) return
    setError(''); setBusy(true)
    try {
      await apiUpload('/driver/documents/LICENSE', documents.license)
      for (const vehicle of documents.vehicles) await apiUpload('/driver/documents/VEHICLE_PHOTO', vehicle)
      await apiUpload('/driver/documents/ADDRESS_PROOF', documents.address)
      onAuthenticated(registeredDriver)
    } catch (reason) { setError((reason as Error).message) }
    finally { setBusy(false) }
  }

  const registrationField = (label: string, key: 'name'|'email'|'phone'|'password'|'license_number'|'license_expiry', type = 'text') => <label className="field"><span>{label}</span><div><UserRound/><input type={type} value={registration[key]} onChange={(event)=>setRegistration({...registration,[key]:event.target.value})} required /></div></label>

  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
    <section className={`login-modal ${mode==='register'?'registration-modal':''}`} role="dialog" aria-modal="true" aria-labelledby="auth-modal-title">
      <button className="modal-close" aria-label="Close account dialog" onClick={onClose}><X /></button>
      {registeredDriver ? <><p className="eyebrow">DRIVER VERIFICATION</p><h1 id="auth-modal-title">Upload your documents</h1><p>Submit clear files for admin review before you can receive trips.</p><form className="driver-documents-form" onSubmit={uploadDocuments}>
        <label className="file-field"><FileCheck2/><span>Driving licence</span><input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" required onChange={(event)=>setDocuments({...documents,license:event.target.files?.[0]??null})}/></label>
        <label className="file-field"><CarFront/><span>Car photos</span><input type="file" accept="image/jpeg,image/png,image/webp" multiple required onChange={(event)=>setDocuments({...documents,vehicles:Array.from(event.target.files??[])})}/></label>
        <label className="file-field"><MapPin/><span>Address proof</span><input type="file" accept="application/pdf,image/jpeg,image/png,image/webp" required onChange={(event)=>setDocuments({...documents,address:event.target.files?.[0]??null})}/></label>
        {error&&<div className="error-state"><ShieldCheck/><div><strong>Upload failed</strong><p>{error}</p></div></div>}<button className="button wide" disabled={busy}>{busy?'Uploading...':'Submit for admin approval'} <ArrowRight/></button>
      </form></> : mode === 'login' ? <><p className="eyebrow">WELCOME BACK</p><h1 id="auth-modal-title">Sign in to RideX</h1><p>Manage your journeys from one secure account.</p>
      <form onSubmit={login}>
        <label className="field"><span>Email address</span><div><UserRound /><input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoFocus /></div></label>
        <label className="field"><span>Password</span><div><ShieldCheck /><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required /></div></label>
        <Link className="forgot-link modal-forgot" to="/forgot-password" onClick={onClose}>Forgot password?</Link>
        {error && <div className="error-state"><ShieldCheck /><div><strong>Unable to sign in</strong><p>{error}</p></div></div>}
        <button className="button wide" disabled={busy}>{busy?'Signing in...':'Sign in'} <ArrowRight /></button>
      </form>
      <button className="modal-register" onClick={()=>{setMode('register');setError('')}}>Create an account</button></> : <><p className="eyebrow">JOIN RIDEX</p><h1 id="auth-modal-title">Create your account</h1><p>Register as a customer or apply to drive with RideX.</p><div className="segmented auth-role"><button type="button" className={registration.role==='CUSTOMER'?'active':''} onClick={()=>setRegistration({...registration,role:'CUSTOMER'})}>Customer</button><button type="button" className={registration.role==='DRIVER'?'active':''} onClick={()=>setRegistration({...registration,role:'DRIVER'})}>Driver</button></div><form className="registration-form" onSubmit={register}>{registrationField('Full name','name')}{registrationField('Email address','email','email')}{registrationField('Mobile number','phone','tel')}{registrationField('Password','password','password')}{registration.role==='DRIVER'&&<>{registrationField('Driving licence number','license_number')}{registrationField('Licence expiry','license_expiry','date')}</>}{error&&<div className="error-state"><ShieldCheck/><div><strong>Unable to register</strong><p>{error}</p></div></div>}<button className="button wide" disabled={busy}>{busy?'Creating account...':registration.role==='DRIVER'?'Continue to documents':'Create customer account'} <ArrowRight/></button></form><button className="modal-register" onClick={()=>{setMode('login');setError('')}}>Already registered? Sign in</button></>}
    </section>
  </div>
}