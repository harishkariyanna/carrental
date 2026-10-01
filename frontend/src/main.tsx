import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './ridex.css'
import './professional.css'
import RideXApp from './RideXApp.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RideXApp />
  </StrictMode>,
)
