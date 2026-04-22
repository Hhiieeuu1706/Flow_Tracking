import type { FlowType } from '../types'

/**
 * @param strength Raw strength from -10 to 10
 */
export function flowColor(strength: number, alphaOverride?: number) {
  // Logic:
  // 0: White (rgba(255,255,255,1))
  // 0 to +-2: Interpolate White(1) to Color(0.3)
  // +-2 to +-10: Color with opacity 0.3 to 1.0

  if (strength === 0) return `rgba(255, 255, 255, ${alphaOverride ?? 1})`

  const isPositive = strength > 0
  const absStrength = Math.min(10, Math.abs(strength))
  
  // Vibrant Green/Red (Tailwind-like)
  const [r, g, b] = isPositive ? [34, 197, 94] : [239, 68, 68]

  if (absStrength < 2) {
    const t = absStrength / 2
    // Interpolate RGB from 255 to target
    const nr = Math.round(255 + (r - 255) * t)
    const ng = Math.round(255 + (g - 255) * t)
    const nb = Math.round(255 + (b - 255) * t)
    // Interpolate Alpha from 1.0 down to 0.3
    const na = alphaOverride ?? (1 + (0.3 - 1) * t)
    return `rgba(${nr},${ng},${nb},${Number(na).toFixed(2)})`
  } else {
    const t = (absStrength - 2) / 8
    // Opacity increases from 0.3 to 1.0
    const na = alphaOverride ?? (0.3 + (1 - 0.3) * t)
    return `rgba(${r},${g},${b},${Number(na).toFixed(2)})`
  }
}



export function shouldHighlight(type: FlowType) {
  return type === 'FORCE' || type === 'SQUEEZE' || type === 'MIXED' || type === 'OTHER' || type === 'EVENT'
}

export function candleOpacity(type: FlowType) {
  if (type === 'FORCE') return 1
  if (type === 'SQUEEZE') return 0.6
  if (type === 'MIXED') return 1
  if (type === 'OTHER') return 0.3
  if (type === 'EVENT') return 0.4
  return 1
}

