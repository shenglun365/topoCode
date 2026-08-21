export function useToast() {
  function show(msg: string, duration = 3000) {
    const el = document.createElement('div')
    el.textContent = msg
    Object.assign(el.style, {
      position: 'fixed', bottom: '24px', left: '50%', transform: 'translateX(-50%)',
      background: '#333', color: '#fff', padding: '10px 20px', borderRadius: '8px',
      fontSize: '14px', zIndex: '9999', boxShadow: '0 4px 12px rgba(0,0,0,0.2)',
      maxWidth: '80vw', textAlign: 'center', pointerEvents: 'none',
    })
    document.body.appendChild(el)
    setTimeout(() => el.remove(), duration)
  }
  return { toast: show }
}
