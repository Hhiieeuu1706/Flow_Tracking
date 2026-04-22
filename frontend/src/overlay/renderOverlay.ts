import type { IChartApi, Time } from 'lightweight-charts'
import { flowColor } from '../flow/colors'

import type { AssetSymbol, FlowObject, Session } from '../types'

type RenderOverlayArgs = {
  chart: IChartApi
  overlayEl: HTMLElement
  sessions: Session[]
  flowsByDate: Map<string, FlowObject>
  dayBoundaries: number[] // unix seconds (shared across all symbols)
  symbol: AssetSymbol
  onClickAdd: (s: Session) => void // kept for API compat; buttons rendered elsewhere
}

function visibleEndpointToUnixSeconds(v: any): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v
  if (v && typeof v === 'object' && typeof v.year === 'number' && typeof v.month === 'number' && typeof v.day === 'number') {
    const d = new Date(v.year, v.month - 1, v.day, 0, 0, 0, 0)
    return Math.floor(d.getTime() / 1000)
  }
  return null
}

export function renderOverlay({
  chart,
  overlayEl,
  sessions,
  flowsByDate,
  dayBoundaries,
  symbol,
  onClickAdd,
}: RenderOverlayArgs) {
  void onClickAdd
  void symbol
  const ts = chart.timeScale()
  overlayEl.innerHTML = ''

  const vr = (ts as any).getVisibleRange?.() as undefined | { from: any; to: any }
  const visibleFrom = vr?.from != null ? visibleEndpointToUnixSeconds(vr.from) : null
  const visibleTo = vr?.to != null ? visibleEndpointToUnixSeconds(vr.to) : null

  for (const t of dayBoundaries) {
    if (visibleFrom != null && visibleTo != null) {
      if (t < visibleFrom || t > visibleTo) continue
    }
    const x = ts.timeToCoordinate(t as unknown as Time)
    if (x == null) continue
    const line = document.createElement('div')
    line.style.position = 'absolute'
    line.style.top = '0px'
    line.style.left = `${x}px`
    line.style.width = '1.5px'
    line.style.height = '100%'
    line.style.background = 'rgba(255,255,255,0.12)'
    line.style.pointerEvents = 'none'
    overlayEl.appendChild(line)
  }

  const renderedScoreDates = new Set<string>()
  for (const s of sessions) {
    if (visibleFrom != null && visibleTo != null) {
      if (s.endTime < visibleFrom || s.startTime > visibleTo) continue
    }

    const flow = flowsByDate.get(s.date)
    const displayState = s.regime || flow?.state
    
    if (displayState) {
      const xStart = ts.timeToCoordinate(s.startTime as unknown as Time)
      const left = xStart != null ? xStart + 10 : 10

      const stateTag = document.createElement('div')
      stateTag.style.position = 'absolute'
      stateTag.style.left = `${left}px`
      stateTag.style.top = '10px'
      stateTag.style.fontSize = '12px'
      stateTag.style.fontWeight = '900'
      stateTag.style.letterSpacing = '0.5px'
      stateTag.style.color = s.regime ? 'rgba(192,132,252,1)' : 'rgba(255,255,255,0.9)'
      stateTag.style.textShadow = '0 1px 4px rgba(0,0,0,0.9)'
      stateTag.style.pointerEvents = 'none'
      stateTag.style.whiteSpace = 'nowrap'
      stateTag.style.textTransform = 'uppercase'
      stateTag.textContent = displayState
      overlayEl.appendChild(stateTag)
    }

    const score = flow?.flow.strength
    
    if (score !== undefined && score !== null && !renderedScoreDates.has(s.date)) {
      renderedScoreDates.add(s.date)
      const xStart = ts.timeToCoordinate(s.startTime as unknown as Time)
      const xEnd = ts.timeToCoordinate(s.endTime as unknown as Time)
      if (xStart != null && xEnd != null) {
        const xMid = (xStart + xEnd) / 2
        const color = flowColor(score, 1) // Opaque color for text readability
        const borderColor = flowColor(score, 0.3)
        
        const scoreTag = document.createElement('div')
        scoreTag.style.position = 'absolute'
        scoreTag.style.left = `${xMid - 15}px`
        scoreTag.style.bottom = '40px'
        scoreTag.style.padding = '2px 6px'
        scoreTag.style.borderRadius = '4px'
        scoreTag.style.background = 'rgba(0,0,0,0.6)'
        scoreTag.style.border = `1px solid ${borderColor}`
        scoreTag.style.fontSize = '14px'
        scoreTag.style.fontWeight = '900'
        scoreTag.style.color = color
        scoreTag.style.textShadow = '0 1px 4px rgba(0,0,0,1)'
        scoreTag.style.pointerEvents = 'none'
        scoreTag.textContent = (score > 0 ? '+' : '') + score.toFixed(1)
        overlayEl.appendChild(scoreTag)
      }
    }
  }
}
