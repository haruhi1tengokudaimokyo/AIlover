import fallback from '@/assets/default-avatar.svg'

export function avatarFallback(event) {
  const image = event.target
  image.onerror = null
  if (image.src !== fallback && image.getAttribute('src') !== fallback) image.src = fallback
}
