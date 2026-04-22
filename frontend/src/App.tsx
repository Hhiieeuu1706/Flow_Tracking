import { useEffect, useRef, useState } from 'react'

import { Button } from './components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from './components/ui/dialog'

import { buildSessions } from './flow/session'
import {
  flowKey,
  getBarsFromCache,
  getCachedCoverage,
  loadFlow,
  saveFlow,
  upsertBarsToCache,
  resetAllStrengths,
  clearAllFlowData,
  getBackupFlowData,
  restoreFlowData,
  clearBarsCache,
} from './flow/storage'
import type { AssetSymbol, LwcBar, LogicalRange, Session } from './types'
import { ChartPanel } from './components/ChartPanel'
import { flowColor } from './flow/colors'

const SYMBOLS: AssetSymbol[] = ['US30', 'USTEC', 'US500']
const FETCH_ORDER: AssetSymbol[] = ['USTEC', 'US500', 'US30']
const QUICK_FETCH_DAYS = 360

async function fetchWithTimeout(input: string, timeoutMs: number): Promise<Response> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => {
    // Provide explicit reason to avoid opaque "aborted without reason".
    controller.abort(new Error(`Timeout after ${Math.floor(timeoutMs / 1000)}s`))
  }, timeoutMs)
  try {
    return await fetch(input, { signal: controller.signal })
  } finally {
    window.clearTimeout(timeoutId)
  }
}

type SymbolState = {
  sessions: Session[]
  error: string | null
}

function App() {
  const [rangeDays, setRangeDays] = useState(360)
  const [loading, setLoading] = useState(false)
  const [lastFetchDebug, setLastFetchDebug] = useState<string | null>(null)
  const [bySymbol, setBySymbol] = useState<Partial<Record<AssetSymbol, SymbolState>>>(() => ({
    'US30': { sessions: [], error: null },
    'USTEC': { sessions: [], error: null },
    'US500': { sessions: [], error: null },
  }))

  const [modalOpen, setModalOpen] = useState(false)
  const [activeSession, setActiveSession] = useState<Session | null>(null)

  const [flowStrength, setFlowStrength] = useState('0')
  const [flowNote, setFlowNote] = useState('')

  const [strengthCheckActive, setStrengthCheckActive] = useState(false)
  const [ratioSessions, setRatioSessions] = useState<Session[]>([])
  const [lastFlowBackup, setLastFlowBackup] = useState<any[] | null>(null)

  const [cacheCleared, setCacheCleared] = useState(false)

  const [syncLogicalRange, setSyncLogicalRange] = useState<LogicalRange>(null)
  const rangeSourceRef = useRef<AssetSymbol | null>(null)
  const [dataRev, setDataRev] = useState(0)
  const [scrollRev, setScrollRev] = useState(0)
  const backfillRunningRef = useRef(false)
  const latestRangeDaysRef = useRef(rangeDays)

  const fmtElapsed = (ms: number) => `${Math.max(0, ms / 1000).toFixed(1)}s`

  // Calculate ratio sessions (DJ30 / USTEC)
  const calculateRatioSessions = () => {
    const dj30Sessions = bySymbol['US30']?.sessions || []
    const ustecSessions = bySymbol['USTEC']?.sessions || []

    if (dj30Sessions.length === 0 || ustecSessions.length === 0) return []

    // Create a map of USTEC bars by time for quick lookup
    const ustecBarsByTime = new Map<number, LwcBar>()
    for (const session of ustecSessions) {
      for (const bar of session.bars) {
        ustecBarsByTime.set(bar.time, bar)
      }
    }

    // Calculate ratio bars for DJ30 sessions
    const ratioSessions: Session[] = []
    for (const dj30Session of dj30Sessions) {
      const ratioBars: LwcBar[] = []
      for (const dj30Bar of dj30Session.bars) {
        const ustecBar = ustecBarsByTime.get(dj30Bar.time)
        if (ustecBar && ustecBar.close !== 0) {
          const ratio = dj30Bar.close / ustecBar.close
          const ratioOpen = dj30Bar.open / ustecBar.open
          const ratioHigh = dj30Bar.high / ustecBar.low // Use low for denominator to get max ratio
          const ratioLow = dj30Bar.low / ustecBar.high // Use high for denominator to get min ratio
          
          ratioBars.push({
            time: dj30Bar.time,
            open: ratioOpen,
            high: Math.max(ratioHigh, ratioLow), // Ensure high > low
            low: Math.min(ratioHigh, ratioLow),
            close: ratio,
          })
        }
      }
      
      if (ratioBars.length > 0) {
        ratioSessions.push({
          asset: 'US30 / USTEC',
          date: dj30Session.date,
          startTime: dj30Session.startTime,
          endTime: dj30Session.endTime,
          bars: ratioBars,
        })
      }
    }

    return ratioSessions
  }

  // Calculate actual days of data currently displayed
  const calculateActualDays = () => {
    let minTime = Infinity
    let maxTime = -Infinity
    let hasData = false

    for (const sym of SYMBOLS) {
      const sessions = bySymbol[sym]?.sessions || []
      for (const session of sessions) {
        if (session.bars && session.bars.length > 0) {
          hasData = true
          minTime = Math.min(minTime, session.bars[0].time)
          maxTime = Math.max(maxTime, session.bars[session.bars.length - 1].time)
        }
      }
    }

    if (!hasData) return 0
    const daysDiff = Math.ceil((maxTime - minTime) / (60 * 60 * 24))
    return daysDiff + 1 // Include both start and end day
  }

  const actualDays = calculateActualDays()

  const legend = {
    weak: flowColor(-8), // strong red
    strong: flowColor(8), // strong green
  }

  useEffect(() => {
    latestRangeDaysRef.current = rangeDays
  }, [rangeDays])

  // Update ratio sessions when DJ30 or USTEC changes
  useEffect(() => {
    setRatioSessions(calculateRatioSessions())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bySymbol])

  async function backfillFullRange(days: number) {
    if (backfillRunningRef.current) return
    backfillRunningRef.current = true
    const startedAt = Date.now()
    try {
      const end = new Date()
      const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000)
      const qsBase = new URLSearchParams({
        from: start.toISOString(),
        to: end.toISOString(),
      })

      for (let i = 0; i < FETCH_ORDER.length; i++) {
        const sym = FETCH_ORDER[i]
        const reqId = `bg-${Date.now()}-${sym}-${Math.random().toString(36).slice(2, 8)}`
        const qs = new URLSearchParams(qsBase)
        qs.set('symbols', sym)
        qs.set('req_id', reqId)
        setLastFetchDebug(`BACKFILL ${i + 1}/${FETCH_ORDER.length} • ${sym} • ${fmtElapsed(Date.now() - startedAt)}`)

        try {
          const res = await fetchWithTimeout(`/api/bars-multi?${qs.toString()}`, 30000)
          const text = await res.text()
          let payload: { barsBySymbol?: Record<string, LwcBar[]>; error?: string } = {}
          try {
            payload = JSON.parse(text)
          } catch {
            // keep payload as {}
          }
          if (!res.ok || !payload.barsBySymbol) continue

          const bars = payload.barsBySymbol?.[sym] || []
          if (bars.length > 0) {
            await upsertBarsToCache(sym, 'H1', bars)
            if (latestRangeDaysRef.current === days) {
              setBySymbol((prev) => ({
                ...prev,
                [sym]: { sessions: buildSessions(sym, bars), error: null },
              }))
            }
          }
        } catch {
          // best-effort backfill; ignore per-symbol failures
        }
      }
      if (latestRangeDaysRef.current === days) {
        setDataRev((x) => x + 1)
      }
      setLastFetchDebug(`BACKFILL done • ${days}d • elapsed=${fmtElapsed(Date.now() - startedAt)}`)
    } finally {
      backfillRunningRef.current = false
    }
  }

  async function fetchBarsAll(force = false) {
    if (loading) return
    setLoading(true)
    setLastFetchDebug(null)
    let shouldBackfill = false
    try {
      const effectiveDays = Math.min(rangeDays, QUICK_FETCH_DAYS)
      shouldBackfill = rangeDays > effectiveDays
      const end = new Date()
      const start = new Date(end.getTime() - effectiveDays * 24 * 60 * 60 * 1000)
      const fromSec = Math.floor(start.getTime() / 1000)
      const toSec = Math.floor(end.getTime() / 1000)

      // 1) Render immediately from local cache if available
      const cachedBySymbol = await Promise.all(
        SYMBOLS.map(async (sym) => {
          const bars = await getBarsFromCache(sym, 'H1', fromSec, toSec)
          return { sym, bars }
        }),
      )
      setBySymbol((prev) => {
        const next = { ...prev }
        for (const { sym, bars } of cachedBySymbol) {
          if (bars.length > 0) next[sym] = { sessions: buildSessions(sym, bars), error: null }
        }
        return next
      })

      // 2) Fetch only if cache doesn't cover the requested range
      const needFetch: AssetSymbol[] = []
      if (force) {
        needFetch.push(...SYMBOLS)
      } else {
        for (const sym of SYMBOLS) {
          const cov = await getCachedCoverage(sym, 'H1', fromSec, toSec)
          if (!cov.hasAny || (cov.min != null && cov.min > fromSec) || (cov.max != null && cov.max < toSec)) {
            needFetch.push(sym)
          }
        }
        if (needFetch.length === 0) return
      }

      // 3) Fetch/update symbol-by-symbol so one stuck symbol doesn't block all.
      const startedAt = Date.now()
      const okSymbols: AssetSymbol[] = []
      const failedSymbols: Array<{ sym: AssetSymbol; msg: string }> = []
      const lastBySymbol: Partial<Record<AssetSymbol, string>> = {}
      const orderedNeedFetch = [...needFetch].sort(
        (a, b) => FETCH_ORDER.indexOf(a) - FETCH_ORDER.indexOf(b),
      )

      for (let i = 0; i < orderedNeedFetch.length; i++) {
        const sym = orderedNeedFetch[i]
        const reqId = `${Date.now()}-${sym}-${Math.random().toString(36).slice(2, 8)}`
        const qs = new URLSearchParams({
          symbols: sym,
          from: start.toISOString(),
          to: end.toISOString(),
          req_id: reqId,
        })
        if (force) qs.set('force', '1')

        setLastFetchDebug(`RUNNING ${i + 1}/${orderedNeedFetch.length} • ${sym} • ${fmtElapsed(Date.now() - startedAt)}`)

        let progressTimer: number | null = window.setInterval(async () => {
          try {
            const p = await fetch(`/api/bars-progress/${encodeURIComponent(reqId)}`, { cache: 'no-store' })
            if (p.status === 404) {
              // Backend may be an older build without progress endpoint; stop polling to avoid console spam.
              if (progressTimer != null) {
                window.clearInterval(progressTimer)
                progressTimer = null
              }
              return
            }
            if (!p.ok) return
            const j = (await p.json()) as { stage?: string; detail?: string | null }
            const stage = j.stage || 'running'
            const detail = j.detail ? ` • ${j.detail}` : ''
            setLastFetchDebug(
              `RUNNING ${i + 1}/${orderedNeedFetch.length} • ${sym} • ${fmtElapsed(Date.now() - startedAt)} • ${stage}${detail}`,
            )
          } catch {
            // keep previous status
          }
        }, 800)

        try {
          const res = await fetchWithTimeout(`/api/bars-multi?${qs.toString()}`, 30000)

          const text = await res.text()
          let payload: {
            barsBySymbol?: Record<string, LwcBar[]>
            error?: string
          } = {}
          try {
            payload = JSON.parse(text)
          } catch {
            // keep payload as {}
          }
          if (!res.ok || !payload.barsBySymbol) {
            const snippet = text ? text.slice(0, 240) : '(empty response)'
            throw new Error(payload.error || `HTTP ${res.status}: ${snippet}`)
          }

          const bars = payload.barsBySymbol?.[sym] || []
          if (bars.length > 0) {
            await upsertBarsToCache(sym, 'H1', bars)
            const t = bars[bars.length - 1]?.time
            if (t) lastBySymbol[sym] = new Date(t * 1000).toISOString().slice(0, 16).replace('T', ' ')
          }
          setBySymbol((prev) => ({
            ...prev,
            [sym]: { sessions: buildSessions(sym, bars), error: null },
          }))
          okSymbols.push(sym)
        } catch (err) {
          const msg =
            err instanceof Error && err.name === 'AbortError'
              ? 'Fetch timeout after 30s'
              : err instanceof Error
                ? err.message
                : String(err)
          failedSymbols.push({ sym, msg })
          setBySymbol((prev) => ({
            ...prev,
            [sym]: {
              sessions: prev[sym]?.sessions || [],
              error: (prev[sym]?.sessions?.length || 0) > 0 ? null : msg,
            },
          }))
        } finally {
          if (progressTimer != null) {
            window.clearInterval(progressTimer)
            progressTimer = null
          }
        }
      }

      const lastLine = `last(MQL5 UTC) USTEC=${lastBySymbol['USTEC'] || '-'} US30=${lastBySymbol['US30'] || '-'} US500=${lastBySymbol['US500'] || '-'}`
      if (failedSymbols.length === 0) {
        setLastFetchDebug(`OK: ${okSymbols.length}/${orderedNeedFetch.length} symbol(s) • elapsed=${fmtElapsed(Date.now() - startedAt)} • ${lastLine}`)
      } else {
        const failLine = failedSymbols.map((x) => `${x.sym}: ${x.msg}`).join(' | ')
        setLastFetchDebug(
          `PARTIAL: ok=${okSymbols.length}/${orderedNeedFetch.length} • fail=${failedSymbols.length} • elapsed=${fmtElapsed(Date.now() - startedAt)} • ${failLine} • ${lastLine}`,
        )
      }
      // Also scroll charts to latest candle after fetch.
      setScrollRev((x) => x + 1)

      // Force panels to re-read flows/meta and redraw overlay immediately after a fetch.
      setDataRev((x) => x + 1)
    } catch (e) {
      const msg =
        e instanceof Error && e.name === 'AbortError'
          ? 'Fetch timeout after 30s (backend may be busy or MT5 not responding)'
          : e instanceof Error
            ? e.message
            : String(e)
      setLastFetchDebug(`ERROR: ${msg}`)
      // Keep already-rendered sessions from local cache; only surface fetch error.
      setBySymbol((prev) => {
        const next = { ...prev }
        for (const s of SYMBOLS) {
          next[s] = {
            sessions: prev[s]?.sessions || [],
            error: (prev[s]?.sessions?.length || 0) > 0 ? null : msg,
          }
        }
        return next
      })
    } finally {
      setLoading(false)
      if (shouldBackfill) {
        void backfillFullRange(rangeDays)
      }
    }
  }

  async function openFlowModal(s: Session) {
    setActiveSession(s)
    const existing = await loadFlow(s.asset, s.date)
    if (existing) {
      setFlowStrength(existing.flow.strength != null ? existing.flow.strength.toString() : '')
      setFlowNote(existing.note || '')
    } else {
      setFlowStrength('')
      setFlowNote('')
    }
    setModalOpen(true)
  }

  async function commitFlow() {
    if (!activeSession) return
    const parsedStrength = flowStrength.trim() === '' ? null : Number(flowStrength)
    const strength = parsedStrength == null || !Number.isFinite(parsedStrength)
      ? null
      : Math.max(-10, Math.min(10, parsedStrength))
    await saveFlow({
      asset: activeSession.asset,
      date: activeSession.date,
      flow: { type: 'OTHER', strength },
      direction: 'FLAT',
      note: flowNote,
      state: null,
    })
    // Trigger panels to re-render (no re-fetch needed)
    setBySymbol((prev) => ({ ...prev }))
    setDataRev((x) => x + 1)
    setModalOpen(false)
  }

  async function resetStrengths() {
    if (!window.confirm('Xác nhận xóa tất cả strength?')) return
    await resetAllStrengths()
    setBySymbol((prev) => ({ ...prev }))
    setDataRev((x) => x + 1)
  }

  async function clearFlowData() {
    if (!window.confirm('Xác nhận xóa toàn bộ dữ liệu flow đã lưu?')) return
    const backup = await getBackupFlowData()
    setLastFlowBackup(backup)
    await clearAllFlowData()
    setBySymbol((prev) => ({ ...prev }))
    setDataRev((x) => x + 1)
  }

  async function restoreLastClear() {
    if (!lastFlowBackup) return
    if (!window.confirm('Khôi phục dữ liệu flow đã xóa?')) return
    await restoreFlowData(lastFlowBackup)
    setLastFlowBackup(null)
    setBySymbol((prev) => ({ ...prev }))
    setDataRev((x) => x + 1)
  }

  useEffect(() => {
    // Auto-clear BlackBull cache on first startup (migration to ICMarkets)
    if (!cacheCleared) {
      clearBarsCache().then(() => {
        setCacheCleared(true)
        setLastFetchDebug('✓ BlackBull cache cleared. Ready to fetch from ICMarkets. Click "Fetch" to load data.')
      }).catch(err => {
        console.error('Failed to clear cache:', err)
        setCacheCleared(true)
      })
    }
  }, [cacheCleared])

  useEffect(() => {
    // Prefer cache-first startup; avoid forcing MT5 fetch on every load.
    // This keeps UI stable even if MT5 is temporarily busy.
    if (cacheCleared) {
      fetchBarsAll(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheCleared, rangeDays])

  return (
    <div className="h-full bg-black text-zinc-100">
      <div className="mx-auto flex h-full max-w-[1800px] flex-col px-3 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <div className="text-sm font-semibold">Flow Tracking</div>
            <div className="text-xs text-zinc-500">MT5 Daily Sessions</div>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs text-zinc-400">
            <div className="flex items-center gap-2 rounded-md border border-zinc-800 bg-zinc-950/80 px-2 py-1">
              <span
                className="h-3.5 w-3.5 shrink-0 rounded-sm border border-zinc-700"
                style={{ backgroundColor: legend.weak }}
                title="Weak (Low Strength)"
              />
              <span className="text-[10px] text-zinc-300">WEAK</span>
              <span
                className="h-3.5 w-3.5 shrink-0 rounded-sm border border-zinc-700"
                style={{ backgroundColor: legend.strong }}
                title="Strong (High Strength)"
              />
              <span className="text-[10px] text-zinc-300">STRONG</span>
            </div>
            <div className="group relative">
              <button
                type="button"
                className="h-7 rounded-md border border-zinc-700 bg-zinc-900 px-2 text-xs text-zinc-300 hover:bg-zinc-800"
              >
                Guide
              </button>
              <div className="pointer-events-none invisible absolute right-0 top-8 z-50 w-[420px] rounded-md border border-zinc-700 bg-zinc-950 p-3 text-xs text-zinc-300 opacity-0 shadow-xl transition group-hover:visible group-hover:opacity-100">
                <div>
                  <span className="text-zinc-100">Step 1:</span> Click <span className="text-zinc-100">+</span> below
                  day 16 to analyze day 16 cut-off.
                </div>
                <div className="mt-1">
                  <span className="text-zinc-100">Step 2:</span> Click <span className="text-zinc-100">o</span> above
                  day 17 to fill strongest/weakest + tradeability for day 17.
                </div>
              </div>
            </div>
            <button
              type="button"
              className={`h-7 rounded-md border px-2 text-xs ${
                strengthCheckActive
                  ? 'border-amber-600 bg-amber-950 text-amber-200 hover:bg-amber-900'
                  : 'border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800'
              }`}
              onClick={() => setStrengthCheckActive(!strengthCheckActive)}
              title={strengthCheckActive ? 'DJ30/USTEC Ratio' : 'Show strength check'}
            >
              Strength Check
            </button>
            <button
              type="button"
              className="h-7 rounded-md border border-zinc-700 bg-zinc-900 px-2 text-xs text-zinc-300 hover:bg-zinc-800"
              onClick={resetStrengths}
            >
              Reset Strengths
            </button>
            <button
              type="button"
              className="h-7 rounded-md border border-orange-600 bg-orange-950 px-2 text-xs text-orange-300 hover:bg-orange-900"
              onClick={() => {
                if (window.confirm('Clear all bars cache (BlackBull data) and refetch from ICMarkets?')) {
                  clearBarsCache().then(() => {
                    setLastFetchDebug('✓ Cache cleared. Ready to fetch from ICMarkets.')
                    fetchBarsAll(true).catch(err => {
                      setLastFetchDebug(`ERROR: ${err instanceof Error ? err.message : String(err)}`)
                    })
                  })
                }
              }}
              title="Clear BlackBull cache & fetch fresh data from ICMarkets"
            >
              Clear Cache & Refetch
            </button>
            <button
              type="button"
              className="h-7 rounded-md border border-red-600 bg-red-950 px-2 text-xs text-red-300 hover:bg-red-900"
              onClick={clearFlowData}
            >
              Clear All Flow Data
            </button>
            {lastFlowBackup && (
              <button
                type="button"
                className="h-7 rounded-md border border-amber-600 bg-amber-950 px-2 text-xs text-amber-200 hover:bg-amber-900"
                onClick={restoreLastClear}
                title="Restore the last cleared data"
              >
                Restore Last Clear
              </button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <select
              className="h-9 rounded-md border border-zinc-800 bg-zinc-950 px-3 text-sm"
              value={rangeDays}
              onChange={(e) => setRangeDays(Number(e.target.value))}
            >
              <option value={10}>10d</option>
              <option value={30}>30d</option>
              <option value={60}>60d</option>
              <option value={90}>90d</option>
              <option value={180}>180d</option>
              <option value={360} selected>360d</option>
            </select>
            <span className="text-xs text-zinc-400">{actualDays > 0 ? `(${actualDays}d loaded)` : '(no data)'}</span>
            <Button
              variant="secondary"
              onClick={() => {
                fetchBarsAll(true).catch((err) => {
                  // last resort: avoid "Uncaught (in promise) undefined"
                  setLastFetchDebug(`ERROR: ${err instanceof Error ? err.message : String(err)}`)
                })
              }}
              disabled={loading}
              title="Fetch latest bars from MT5"
            >
              {loading ? 'Loading…' : 'Fetch'}
            </Button>
          </div>
        </div>
        {lastFetchDebug && !lastFetchDebug.startsWith('BACKFILL') ? (
          <div className="mt-2 rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-xs text-zinc-300">
            {lastFetchDebug}
          </div>
        ) : null}

        <div className="mt-3 overflow-hidden rounded-xl border border-zinc-800">
          {SYMBOLS.map((s, idx) => {
            const isRatioSlot = idx === 2 && strengthCheckActive
            const sessionsToUse = isRatioSlot ? ratioSessions : (bySymbol[s]?.sessions || [])
            const isRatio = isRatioSlot
            
            return (
              <div key={isRatioSlot ? 'ratio-slot' : s}>
                {bySymbol[s]?.error && !isRatio && (
                  <div className="border-b border-zinc-800 bg-red-950/30 p-3 text-sm text-red-200">
                    {s}: {bySymbol[s]?.error}
                  </div>
                )}
                <ChartPanel
                  symbol={isRatio ? 'US500' : s}
                  sessions={sessionsToUse}
                  syncLogicalRange={syncLogicalRange}
                  rangeSourceRef={rangeSourceRef}
                  dayBoundaries={(bySymbol['USTEC']?.sessions || []).map((ss) => ss.startTime)}
                  renderSharedPlus={s === 'USTEC' && !isRatio}
                  dataRev={dataRev}
                  scrollToEndRev={scrollRev}
                  isRatioChart={isRatio}
                  onLogicalRangeChange={(sym, range) => {
                    rangeSourceRef.current = sym
                    setSyncLogicalRange(range)
                  }}
                  onClickAdd={openFlowModal}
                />
              </div>
            )
          })}
        </div>

        <div className="mt-2 text-xs text-zinc-500">
          Click <span className="text-zinc-300">+</span> at the bottom of a session to attach flow.
        </div>
      </div>

      <Dialog open={modalOpen} onOpenChange={setModalOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {activeSession ? `${activeSession.asset} — ${activeSession.date}` : 'Flow'}
            </DialogTitle>
            <DialogDescription>Saved into localStorage key: {activeSession ? flowKey(activeSession.asset, activeSession.date) : ''}</DialogDescription>
          </DialogHeader>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <div className="text-xs text-zinc-400">Strength (-10–10)</div>
              <input
                className="h-9 w-full rounded-md border border-zinc-800 bg-zinc-950 px-3 text-sm"
                type="number"
                value={flowStrength}
                onChange={(e) => setFlowStrength(e.target.value)}
              />
            </div>
            <div className="col-span-2 space-y-1">
              <div className="text-xs text-zinc-400">Note</div>
              <textarea
                className="min-h-[84px] w-full resize-y rounded-md border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm"
                value={flowNote}
                onChange={(e) => setFlowNote(e.target.value)}
                placeholder="Ex: Dealer short gamma"
              />
            </div>
          </div>

          <div className="mt-4 flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setModalOpen(false)}>
              Cancel
            </Button>
            <Button onClick={commitFlow} disabled={!activeSession}>
              Save
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default App
