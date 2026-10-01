import { useEffect, useRef } from 'react'
import lottie from 'lottie-web/build/player/lottie_light'
import { ArrowRight } from 'lucide-react'
import bookingCarAnimation from '../assets/booking-car.json'

interface BookingSearchButtonProps {
  type?: 'button' | 'submit'
  onClick?: () => void
}

export function BookingSearchButton({ type = 'button', onClick }: BookingSearchButtonProps) {
  const animationRef = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!animationRef.current) return
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const animation = lottie.loadAnimation({ container: animationRef.current, renderer: 'svg', loop: !reduceMotion, autoplay: !reduceMotion, animationData: structuredClone(bookingCarAnimation) })
    if (reduceMotion) animation.goToAndStop(45, true)
    return () => animation.destroy()
  }, [])
  return <button className="button booking-search-button" type={type} onClick={onClick}>
    <span ref={animationRef} className="booking-search-animation" aria-hidden="true"/>
    <span>Search Available Cars</span>
    <ArrowRight/>
  </button>
}
