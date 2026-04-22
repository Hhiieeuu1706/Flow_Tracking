import { useEffect, useState, useMemo } from 'react'
import { ChartPanel } from '../components/ChartPanel'
import type { AssetSymbol, LogicalRange, Session } from '../types'
import { buildSessions } from '../flow/session'
import { upsertBarsToCache } from '../flow/storage'
import { callFlowCheck, type FlowCheckResponse } from './flowCheckApi'

async function fetchWithTimeout(input: string, timeoutMs: number): Promise<Response> {
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => {
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
  loading: boolean
}

const EXTENDED_ASSETS = [
  { symbol: 'DXY', label: 'DXY' },
  { symbol: 'UST10Y', label: 'US10Y' },
  { symbol: 'VIX', label: 'VIX' },
  { symbol: 'US500', label: 'NQ/EQ' },
  { symbol: 'US30', label: 'Dow Jones' },
  { symbol: 'BTCUSD', label: 'Bitcoin' },
  { symbol: 'XAUUSD', label: 'Gold' },
]

const HISTORY_CACHE_KEY = 'flow_check_history_v1'

export function FlowCheckCharts() {
  const [loading, setLoading] = useState(true)
  const [multiResults, setMultiResults] = useState<FlowCheckResponse[]>([])
  const [error, setError] = useState<string | null>(null)
  const [syncLogicalRange, setSyncLogicalRange] = useState<LogicalRange>(null)
  const [dataRev, setDataRev] = useState(0)
  const [calcProgress, setCalcProgress] = useState(0)
  const [calcTotal, setCalcTotal] = useState(360)

  const [bySymbol, setBySymbol] = useState<Record<string, SymbolState>>(() => {
    const init: Record<string, SymbolState> = {}
    EXTENDED_ASSETS.forEach(({ symbol }) => {
      init[symbol] = { sessions: [], error: null, loading: true }
    })
    return init
  })

  const todayStr = useMemo(() => new Date().toISOString().split('T')[0], [])

  const fetchChartData = async (forceRefreshHistory = false) => {
    setLoading(true)
    setError(null)
    setCalcProgress(0)

    try {
      const rangeDays = 360
      const endTime = new Date()
      endTime.setDate(endTime.getDate() + 1)
      const startTime = new Date(endTime)
      startTime.setDate(startTime.getDate() - rangeDays)

      const startSec = Math.floor(startTime.getTime() / 1000)
      const endSec = Math.floor(endTime.getTime() / 1000)

      // Fetch all assets
      await Promise.all(EXTENDED_ASSETS.map(async ({ symbol }) => {
        try {
          const qs = new URLSearchParams({
            symbols: symbol,
            timeframe: 'H1',
            fromSec: startSec.toString(),
            toSec: endSec.toString(),
            from: startSec.toString(),
            to: endSec.toString(),
          })

          const res = await fetchWithTimeout(`/api/bars-multi?${qs}`, 35000)
          if (!res.ok) {
              const errBody = await res.json().catch(() => ({ error: `HTTP ${res.status}` }))
              throw new Error(errBody.error || `HTTP ${res.status}`)
          }

          const data = (await res.json()) as { barsBySymbol?: Record<string, any[]> }
          const bars = data.barsBySymbol?.[symbol] || []

          if (bars.length > 0) {
            await upsertBarsToCache(symbol, 'H1', bars)
          }

          setBySymbol((prev) => ({
            ...prev,
            [symbol]: {
              sessions: buildSessions(symbol as AssetSymbol, bars),
              error: null,
              loading: false,
            },
          }))
        } catch (err) {
          const msg = err instanceof Error ? err.message : String(err)
          setBySymbol((prev) => ({
            ...prev,
            [symbol]: {
              sessions: prev[symbol]?.sessions || [],
              error: msg,
              loading: false,
            },
          }))
        }
      }))

      setDataRev(v => v + 1)

      // 🧠 Caching & History Calculation
      const calcDays = 360
      setCalcTotal(calcDays)
      const cachedHistory = JSON.parse(localStorage.getItem(HISTORY_CACHE_KEY) || '{}')
      const finalResults: FlowCheckResponse[] = []
      
      for (let i = 0; i < calcDays; i++) {
        const d = new Date()
        d.setDate(d.getDate() - i)
        const dStr = d.toISOString().split('T')[0]
        
        let flowRes: FlowCheckResponse | null = null
        
        // Skip API if cached (except for last 2 days)
        if (!forceRefreshHistory && i > 1 && cachedHistory[dStr]) {
            flowRes = cachedHistory[dStr]
        } else {
            try {
                // eslint-disable-next-line no-await-in-loop
                flowRes = await callFlowCheck(dStr)
                if (flowRes) cachedHistory[dStr] = flowRes
            } catch (e) {
                console.error(`Flow check failed for ${dStr}`, e)
            }
        }

        if (flowRes) {
            finalResults.push({ ...flowRes, date: dStr } as any)
            
            // Update sessions in real-time
            setBySymbol((prev) => {
                const updated = { ...prev };
                const targetSymbols: AssetSymbol[] = ['USTEC', 'US500', 'US30'];
                targetSymbols.forEach(sym => {
                    if (updated[sym]) {
                        updated[sym].sessions = updated[sym].sessions.map(s => {
                            if (s.date === dStr) {
                                return { ...s, flowScore: flowRes!.Score, regime: flowRes!.Regime };
                            }
                            return s;
                        });
                    }
                });
                return updated;
            });
        }
        
        setCalcProgress(i + 1)
        if (i > 0 && i % 10 === 0) {
            localStorage.setItem(HISTORY_CACHE_KEY, JSON.stringify(cachedHistory))
        }
      }
      localStorage.setItem(HISTORY_CACHE_KEY, JSON.stringify(cachedHistory))
      setMultiResults(finalResults)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchChartData()
  }, [])

  const dayBoundaries = useMemo(() => {
      const mainSym = bySymbol['US500']?.sessions.length > 0 ? 'US500' : 'DXY'
      return bySymbol[mainSym]?.sessions?.map((s) => s.startTime) || []
  }, [bySymbol])

  const progressPercent = Math.round((calcProgress / calcTotal) * 100)

  return (
    <div className="h-full flex flex-col bg-black text-zinc-100 font-sans select-none">
      {/* Header with Results & Progress */}
      <div className="flex border-b border-zinc-900 bg-black sticky top-0 z-50">
           <div className="p-3 border-r border-zinc-900 flex flex-col justify-center min-w-[140px]">
                <div className="text-[10px] font-black text-purple-500 uppercase tracking-tighter">Flow Intelligence</div>
                <div className="text-[9px] text-zinc-600 font-bold uppercase tracking-widest">{todayStr}</div>
                
                {calcProgress < calcTotal && calcProgress > 0 && !loading && (
                    <div className="mt-2">
                        <div className="flex justify-between text-[8px] font-black text-zinc-500 mb-0.5">
                            <span>SYNCING HISTORY</span>
                            <span>{progressPercent}%</span>
                        </div>
                        <div className="w-full h-1 bg-zinc-900 rounded-full overflow-hidden">
                            <div className="h-full bg-purple-600 transition-all duration-300" style={{ width: `${progressPercent}%` }} />
                        </div>
                    </div>
                )}

                <button 
                    onClick={() => fetchChartData(true)}
                    disabled={loading}
                    className="mt-2 text-[10px] font-bold bg-zinc-900 hover:bg-purple-900/40 text-zinc-400 py-1 rounded border border-zinc-800 transition-all disabled:opacity-20"
                >
                    {loading ? 'INITIALIZING...' : 'FORCE REFRESH'}
                </button>
           </div>
           
           <div className="flex-1 overflow-x-auto custom-scrollbar flex p-2 gap-2">
                {multiResults.length === 0 && Array.from({length: 6}).map((_, i) => (
                    <div key={i} className="min-w-[140px] h-[60px] bg-zinc-900/20 rounded border border-zinc-900 animate-pulse" />
                ))}
                {multiResults.slice(0, 14).map((r: any) => (
                    <div key={r.date} className={`min-w-[160px] p-2 rounded border transition-all ${r.Score > 0.5 ? 'bg-green-500/5 border-green-500/20' : r.Score < -0.5 ? 'bg-red-500/5 border-red-500/20' : 'bg-zinc-900/40 border-zinc-800'}`}>
                        <div className="flex justify-between items-center mb-1">
                            <span className="text-[10px] font-mono text-zinc-500">{r.date.split('-').slice(1).join('/')}</span>
                            <span className={`text-[9px] font-black px-1 rounded ${r.Regime === 'PANIC' ? 'bg-red-500 text-white' : 'bg-purple-500/20 text-purple-400'}`}>{r.Regime}</span>
                        </div>
                        <div className="flex justify-between items-end">
                            <div>
                                <div className="text-[11px] font-black text-zinc-100 tracking-tight leading-none">{r.FlowState}</div>
                                <div className="text-[9px] text-zinc-500 font-bold">{r.DominantFlow}</div>
                            </div>
                            <div className={`text-xl font-black ${r.Score > 0 ? 'text-green-500' : r.Score < 0 ? 'text-red-500' : 'text-zinc-600'}`}>
                                {r.Score > 0 ? '+' : ''}{r.Score.toFixed(1)}
                            </div>
                        </div>
                    </div>
                ))}
           </div>
      </div>

      {error && <div className="p-3 text-xs text-red-500 font-bold bg-red-900/10 border-b border-red-900/30 flex items-center gap-2">
          <span className="bg-red-500 text-white w-4 h-4 flex items-center justify-center rounded-full text-[10px]">!</span>
          SYSTEM ERROR: {error}
      </div>}

      {/* Charts Container */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        <div className="divide-y divide-zinc-900/50">
          {EXTENDED_ASSETS.map(({ symbol, label }) => (
            <div key={symbol} className="bg-black">
              <div className="flex items-center justify-between border-l-2 border-purple-900 bg-gradient-to-r from-zinc-950 to-black px-4 py-2">
                <div className="flex items-center gap-3">
                    <span className="text-[11px] font-black uppercase tracking-[0.2em] text-zinc-400">{label}</span>
                    {bySymbol[symbol]?.loading && <div className="w-1.5 h-1.5 bg-purple-500 rounded-full animate-ping" />}
                </div>
                <div className="flex items-center gap-4">
                  {bySymbol[symbol]?.error && (
                    <span className="text-[10px] text-red-500 font-bold bg-red-500/10 px-2 py-0.5 rounded border border-red-500/20 uppercase tracking-tighter italic">DRIVERS MISSING: {bySymbol[symbol].error}</span>
                  )}
                  {!bySymbol[symbol]?.error && !bySymbol[symbol]?.loading && (
                      <span className="text-[9px] text-zinc-700 font-black tracking-widest uppercase">PIPELINE ACTIVE</span>
                  )}
                </div>
              </div>

              {bySymbol[symbol]?.sessions && bySymbol[symbol].sessions.length > 0 ? (
                <div className="relative" style={{ height: '220px' }}>
                  <ChartPanel
                    symbol={symbol as AssetSymbol}
                    sessions={bySymbol[symbol].sessions}
                    syncLogicalRange={syncLogicalRange}
                    rangeSourceRef={{ current: null }}
                    dayBoundaries={dayBoundaries}
                    renderSharedPlus={false}
                    dataRev={dataRev}
                    scrollToEndRev={1}
                    onLogicalRangeChange={(_, range) => setSyncLogicalRange(range)}
                    onClickAdd={() => {}}
                  />
                  <div className="absolute inset-x-0 bottom-0 h-4 bg-gradient-to-t from-black pointer-events-none opacity-50" />
                </div>
              ) : (
                <div className="h-[220px] flex flex-col items-center justify-center bg-zinc-950/20 border-y border-zinc-900/30">
                  <div className="w-12 h-1 gap-1 flex mb-3">
                      <div className="flex-1 bg-zinc-800 animate-pulse" />
                      <div className="flex-1 bg-zinc-800 animate-pulse" style={{animationDelay: '0.2s'}} />
                      <div className="flex-1 bg-zinc-800 animate-pulse" style={{animationDelay: '0.4s'}} />
                  </div>
                  <div className="text-[9px] text-zinc-600 font-black uppercase tracking-[0.3em] italic">
                    {bySymbol[symbol]?.loading ? 'Initializing Data Stream...' : 'No Connection to Market Nodes'}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
      <style>{`
        .custom-scrollbar::-webkit-scrollbar { width: 5px; height: 5px; }
        .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
        .custom-scrollbar::-webkit-scrollbar-thumb { background: #1a1a1a; border-radius: 10px; }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #222; }
      `}</style>
    </div>
  )
}
