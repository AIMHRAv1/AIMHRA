import { useState } from 'react'
import { IconUser } from './icons'

export default function WorkerAvatar({ src, name, size = 32 }) {
  const [failed, setFailed] = useState(false)
  const style = { width: size, height: size }
  if (src && !failed) {
    return (
      <img
        className="worker-avatar"
        src={src}
        alt={name ? `${name} profile` : 'Healthcare worker profile'}
        style={style}
        onError={() => setFailed(true)}
      />
    )
  }
  return (
    <span className="worker-avatar worker-avatar-placeholder" style={style} aria-hidden="true">
      <IconUser size={Math.round(size * 0.62)} />
    </span>
  )
}
