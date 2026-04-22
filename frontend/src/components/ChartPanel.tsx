import { useEffect, useRef } from 'react'

import { createChartAdapter } from '../chart/lwcAdapter'
import { flowColor } from '../flow/colors'
import { MT5_SERVER_UTC_OFFSET_HOURS } from '../flow/session'
import { flowKey, loadFlowsBulk } from '../flow/storage'
import { renderOverlay } from '../overlay/renderOverlay'
import type { AssetSymbol, FlowObject, LogicalRange, Session } from '../types'

function escapeHtml(s: string) {
  return s
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

type Props = {
  symbol: AssetSymbol
  sessions: Session[]
  syncLogicalRange: LogicalRange
  rangeSourceRef: React.MutableRefObject<AssetSymbol | null>
  onLogicalRangeChange: (symbol: AssetSymbol, range: LogicalRange) => void
  onClickAdd: (s: Session) => void
  dayBoundaries: number[]
  renderSharedPlus?: boolean
  dataRev: number
  scrollToEndRev?: number
  isRatioChart?: boolean
}

export function ChartPanel({
  symbol,
  sessions,
  syncLogicalRange,
  rangeSourceRef,
  onLogicalRangeChange,
  onClickAdd,
  dayBoundaries,
  renderSharedPlus = false,
  dataRev,
  scrollToEndRev,
  isRatioChart = false,
}: Props) {
  const panelRef = useRef<HTMLDivElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const overlayRef = useRef<HTMLDivElement | null>(null)
  const cursorDotRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<ReturnType<typeof createChartAdapter> | null>(null)
  const seriesRef = useRef<ReturnType<ReturnType<typeof createChartAdapter>['createCandlesSeries']> | null>(
    null,
  )

  const suppressSyncRef = useRef(false)
  const didInitialFitRef = useRef(false)
  const lastEmittedLogicalRef = useRef<LogicalRange>(null)
  const flowsByDateRef = useRef<Map<string, FlowObject>>(new Map())
  const overlayRetryRef = useRef(0)

  function createChartIfNeeded() {
    if (chartRef.current || !containerRef.current) return

    const fmt2 = (n: number) => String(n).padStart(2, '0')
    const timeFormatter = (t: any) => {
      // lightweight-charts may pass:
      // - unix seconds number
      // - business day object { year, month, day }
      const sec =
        typeof t === 'number'
          ? t
          : t && typeof t === 'object' && typeof t.year === 'number'
            ? Math.floor(new Date(Date.UTC(t.year, t.month - 1, t.day, 0, 0, 0)).getTime() / 1000)
            : null
      if (sec == null) return ''
      const d = new Date((sec + MT5_SERVER_UTC_OFFSET_HOURS * 3600) * 1000)
      // Use UTC getters because we already applied the desired offset.
      const yyyy = d.getUTCFullYear()
      const mm = fmt2(d.getUTCMonth() + 1)
      const dd = fmt2(d.getUTCDate())
      const hh = fmt2(d.getUTCHours())
      const mi = fmt2(d.getUTCMinutes())
      return `${dd}/${mm}/${String(yyyy).slice(-2)} ${hh}:${mi}`
    }

    const chart = createChartAdapter(containerRef.current, {
      autoSize: true,
      layout: { background: { color: '#050505' }, textColor: '#d4d4d8' },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.05)' },
        horzLines: { color: 'rgba(255,255,255,0.05)' },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
      localization: { timeFormatter },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
    })
    const series = chart.createCandlesSeries({
      upColor: 'rgba(161,161,170,1)',
      downColor: 'rgba(161,161,170,1)',
      borderVisible: false,
      wickUpColor: 'rgba(161,161,170,1)',
      wickDownColor: 'rgba(161,161,170,1)',
    })
    chartRef.current = chart
    seriesRef.current = series
  }

  function setChartData() {
    const chart = chartRef.current
    const series = seriesRef.current
    if (!chart || !series) return
    const byDate = flowsByDateRef.current
    const data: Array<any> = []
    
    // Colors for ratio chart
    const ratioGreen = 'rgba(34, 197, 94, 1)'    // green
    const ratioRed = 'rgba(239, 68, 68, 1)'      // red
    
    for (let i = 0; i < sessions.length; i++) {
      const s = sessions[i]
      
      // For ratio chart: determine daily color from session's daily open/close
      let sessionColor: string | null = null
      if (isRatioChart && s.bars.length > 0) {
        const sessionOpen = s.bars[0].open
        const sessionClose = s.bars[s.bars.length - 1].close
        sessionColor = sessionClose > sessionOpen ? ratioGreen : ratioRed
      }
      
      const flow = byDate.get(s.date)
      const hasStrength = flow?.flow.strength != null
      const strength = hasStrength ? flow.flow.strength! : 0
      const color = hasStrength ? flowColor(strength) : 'rgba(161,161,170,1)'

      for (const b of s.bars) {
        if (isRatioChart && sessionColor) {
          data.push({
            ...b,
            color: sessionColor,
            borderColor: sessionColor,
            wickColor: sessionColor,
          })
        } else if (hasStrength) {
          // Normal mode: Always use the strength-based solid color
          data.push({
            ...b,
            color: color,
            borderColor: color,
            wickColor: color,
          })
        } else {
          // No strength: Default gray
          data.push(b)
        }
      }
      if (sessions[i + 1]) data.push({ time: s.endTime + 1 })
    }
    series.setData(data as any)
  }


  const overlayRaf = useRef<number | null>(null)
  function scheduleOverlayRender() {
    if (overlayRaf.current != null) cancelAnimationFrame(overlayRaf.current)
    overlayRaf.current = requestAnimationFrame(() => {
      overlayRaf.current = null
      const chart = chartRef.current
      const overlay = overlayRef.current
      const panel = panelRef.current
      if (!chart || !overlay) return
      if (!panel) return

      // Render into a temporary container first.
      // During some zoom/pan frames lightweight-charts may return null coordinates; we must NOT
      // clear the existing overlay/buttons in that transient state, or they "disappear".
      const tmpOverlay = document.createElement('div')
      renderOverlay({
        chart: chart.raw,
        overlayEl: tmpOverlay,
        sessions,
        flowsByDate: flowsByDateRef.current,
        dayBoundaries,
        symbol,
        onClickAdd,
      })

      // Render ONE shared + per day on a single "master" panel only
      const newButtonsFrag = document.createDocumentFragment()
      let newPlusCount = 0
      if (renderSharedPlus) {
        const ts = chart.raw.timeScale() as any
        for (const s of sessions) {
          const xStart = ts.timeToCoordinate?.(s.startTime)
          const xEnd = ts.timeToCoordinate?.(s.endTime)
          if (xStart == null || xEnd == null) continue
          const xMid = (xStart + xEnd) / 2
          const btn = document.createElement('button')
          btn.type = 'button'
          btn.dataset['dayPlus'] = '1'
          btn.textContent = '+'
          btn.style.position = 'absolute'
          btn.style.left = `${xMid - 12}px`
          btn.style.bottom = '10px'
          btn.style.zIndex = '35'
          btn.style.width = '24px'
          btn.style.height = '24px'
          btn.style.borderRadius = '999px'
          btn.style.border = '1px solid rgba(255,255,255,0.12)'
          btn.style.background = 'rgba(9,9,11,0.9)'
          btn.style.color = 'rgba(244,244,245,1)'
          btn.style.fontSize = '16px'
          btn.style.lineHeight = '24px'
          btn.style.cursor = 'pointer'

          const flowTipId = `tip_flow_${symbol}_${s.date}`
          const removeFlowTip = () =>
            panel.querySelectorAll(`div[data-tip-id="${flowTipId}"]`).forEach((n) => n.remove())
          btn.addEventListener('mouseenter', () => {
            removeFlowTip()
            const flow = flowsByDateRef.current.get(s.date)

            const tip = document.createElement('div')
            tip.dataset['tipId'] = flowTipId
            tip.dataset['tipKind'] = 'flow'
            tip.style.position = 'absolute'
            tip.style.left = `${Math.max(8, xMid - 140)}px`
            tip.style.bottom = '44px'
            tip.style.width = '280px'
            tip.style.padding = '10px 12px'
            tip.style.borderRadius = '12px'
            tip.style.border = '1px solid rgba(255,255,255,0.12)'
            tip.style.background = 'rgba(0,0,0,0.86)'
            tip.style.color = 'rgba(244,244,245,1)'
            tip.style.fontSize = '12px'
            tip.style.lineHeight = '1.35'
            tip.style.pointerEvents = 'none'
            tip.style.zIndex = '50'

            const flowLine = flow
              ? `${flow.flow.type} ${flow.direction} (strength ${flow.flow.strength})`
              : '(no flow saved)'
            const noteLine = flow?.note ? flow.note : ''
            const stateLine = flow?.state ? `State: ${flow.state}` : ''

            tip.innerHTML = `
              <div style="font-weight:700; margin-bottom:6px;">${s.date}</div>
              <div style="color:rgba(212,212,216,1); margin-bottom:${noteLine ? '6px' : '0'};">${flowLine}</div>
              ${noteLine ? `<div style="color:rgba(161,161,170,1); margin-bottom:${stateLine ? '6px' : '0'};">${escapeHtml(noteLine)}</div>` : ''}
              ${stateLine ? `<div style="color:rgba(161,161,170,1);">${stateLine}</div>` : ''}
            `
            panel.appendChild(tip)
          })
          btn.addEventListener('mouseleave', () => removeFlowTip())

          btn.addEventListener('click', (ev) => {
            ev.preventDefault()
            ev.stopPropagation()
            onClickAdd(s)
          })
          newButtonsFrag.appendChild(btn)
          newPlusCount += 1
        }
      }

      const hadSessions = sessions.length > 0
      const tmpHasOverlay = tmpOverlay.childElementCount > 0
      const tmpButtonsOk = !renderSharedPlus || newPlusCount > 0

      // If a transient frame yields no coordinates, keep previous DOM and retry shortly.
      if (hadSessions && (!tmpHasOverlay || !tmpButtonsOk) && overlayRetryRef.current < 3) {
        overlayRetryRef.current += 1
        requestAnimationFrame(() => scheduleOverlayRender())
        return
      }

      overlayRetryRef.current = 0

      // Commit overlay DOM (replace children)
      overlay.innerHTML = ''
      overlay.append(...Array.from(tmpOverlay.childNodes))

      // Commit buttons DOM
      panel.querySelectorAll('button[data-day-plus="1"]').forEach((n) => n.remove())
      panel.querySelectorAll('div[data-tip-kind="flow"]').forEach((n) => n.remove())
      if (renderSharedPlus) panel.appendChild(newButtonsFrag)
    })
  }

  useEffect(() => {
    createChartIfNeeded()
    const chart = chartRef.current
    if (!chart) return

    const onRange = () => {
      if (!suppressSyncRef.current) {
        const lr = (chart.raw.timeScale() as any).getVisibleLogicalRange?.() as LogicalRange
        if (lr && Number.isFinite(lr.from) && Number.isFinite(lr.to)) {
          const prev = lastEmittedLogicalRef.current
          if (!prev || Math.abs(prev.from - lr.from) >= 0.001 || Math.abs(prev.to - lr.to) >= 0.001) {
            lastEmittedLogicalRef.current = lr
            onLogicalRangeChange(symbol, lr)
          }
        }
      }
      scheduleOverlayRender()
    }

    // Some versions/fire paths update time-range but not logical-range (or vice versa).
    // Subscribe to both so overlays never "disappear" mid-interaction.
    ;(chart.raw.timeScale() as any).subscribeVisibleLogicalRangeChange?.(onRange)
    const onTimeRange = () => scheduleOverlayRender()
    chart.raw.timeScale().subscribeVisibleTimeRangeChange(onTimeRange)

    const onCrosshair = (param: any) => {
      const dot = cursorDotRef.current
      if (!dot) return
      const p = param?.point
      if (!p || p.x == null || p.y == null) {
        dot.style.opacity = '0'
        return
      }
      dot.style.opacity = '1'
      dot.style.transform = `translate(${p.x - 3}px, ${p.y - 3}px)`
    }
    ;(chart.raw as any).subscribeCrosshairMove?.(onCrosshair)

    return () => {
      ;(chart.raw.timeScale() as any).unsubscribeVisibleLogicalRangeChange?.(onRange)
      chart.raw.timeScale().unsubscribeVisibleTimeRangeChange(onTimeRange)
      ;(chart.raw as any).unsubscribeCrosshairMove?.(onCrosshair)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Handle initial fit or preserve user pan when chart updates
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (sessions.length === 0) return

    // Only fitContent on very first load with no prior user pan
    if (!didInitialFitRef.current && !syncLogicalRange) {
      didInitialFitRef.current = true
      chart.raw.timeScale().fitContent()
    }
  }, [sessions, syncLogicalRange])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    if (!syncLogicalRange) return
    if (rangeSourceRef.current === symbol && didInitialFitRef.current) return
    const ts: any = chart.raw.timeScale()
    if (typeof ts.setVisibleLogicalRange !== 'function') return

    suppressSyncRef.current = true
    try {
      ts.setVisibleLogicalRange(syncLogicalRange)
    } finally {
      requestAnimationFrame(() => {
        suppressSyncRef.current = false
        scheduleOverlayRender()
      })
    }
  }, [syncLogicalRange, symbol, rangeSourceRef])

  useEffect(() => {
    createChartIfNeeded()
    setChartData()
    scheduleOverlayRender()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions])

  useEffect(() => {
    let alive = true
    ;(async () => {
      // Shared flow per day: key is date-only.
      const ids = Array.from(new Set(sessions.map((s) => flowKey(s.asset, s.date))))
      const map = await loadFlowsBulk(ids)
      if (!alive) return
      flowsByDateRef.current = map
      setChartData()
      scheduleOverlayRender()
    })()
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions, dataRev])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    // After a manual Fetch, scroll to the newest candle.
    const ts: any = chart.raw.timeScale()
    if (typeof ts.scrollToRealTime === 'function') {
      ts.scrollToRealTime()
    } else {
      ts.fitContent()
    }
    scheduleOverlayRender()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scrollToEndRev])

  return (
    <div
      ref={panelRef}
      className="relative h-[30vh] min-h-[220px] overflow-hidden border-b border-zinc-800 bg-zinc-950"
    >
      <div className="absolute left-3 top-2 z-30 rounded-md bg-black/50 px-2 py-1 text-xs font-semibold text-zinc-200">
        {sessions.length > 0 && sessions[0].asset ? sessions[0].asset : symbol}
      </div>
      <div ref={containerRef} className="absolute inset-0 z-10" />
      <div ref={overlayRef} className="pointer-events-none absolute inset-0 z-20" />
      <div
        ref={cursorDotRef}
        className="pointer-events-none absolute left-0 top-0 z-40 h-[6px] w-[6px] rounded-full border border-zinc-200 bg-black opacity-0"
      />
    </div>
  )
}

