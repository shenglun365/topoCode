let _cachedId: string | null = null
let _initPromise: Promise<string> | null = null

function generateUuid(): string {
  const hex = '0123456789abcdef'
  let id = ''
  for (let i = 0; i < 32; i++) {
    if (i === 8 || i === 12 || i === 16 || i === 20) id += '-'
    id += hex[Math.floor(Math.random() * 16)]
  }
  return id
}

function _syncFallback(): string {
  const key = 'topocode_device_id'
  let id = localStorage.getItem(key)
  if (!id) {
    id = generateUuid()
    localStorage.setItem(key, id)
  }
  _cachedId = id
  return id
}

async function _initDeviceId(): Promise<string> {
  if (_cachedId) return _cachedId
  try {
    if (window.api?.device?.getId) {
      const id = await window.api.device.getId()
      if (id) {
        _cachedId = id
        return id
      }
    }
  } catch {}
  return _syncFallback()
}

export function getDeviceId(): string {
  if (_cachedId) return _cachedId
  if (!_initPromise) {
    _initPromise = _initDeviceId()
  }
  return _syncFallback()
}

export async function ensureDeviceId(): Promise<string> {
  if (_cachedId) return _cachedId
  if (!_initPromise) {
    _initPromise = _initDeviceId()
  }
  return _initPromise.then(() => _cachedId || _syncFallback())
}