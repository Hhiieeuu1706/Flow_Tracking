import { useState } from 'react'
import { Button } from '../components/ui/button'
import { callFlowCheck, type FlowCheckResponse } from './flowCheckApi'

export function FlowCheckPage() {
  const [cutoffDate, setCutoffDate] = useState(
    new Date().toISOString().split('T')[0]
  )
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<FlowCheckResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleRun = async () => {
    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const res = await callFlowCheck(cutoffDate)
      setResult(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4 p-4">
      <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4">
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-zinc-300 mb-1">
              Cutoff Date
            </label>
            <input
              type="date"
              value={cutoffDate}
              onChange={(e) => setCutoffDate(e.target.value)}
              className="h-9 w-full rounded-md border border-zinc-800 bg-zinc-900 px-3 text-sm"
            />
          </div>

          <div>
            <Button
              onClick={handleRun}
              disabled={loading}
              variant="secondary"
            >
              {loading ? 'Analyzing...' : 'Run Flow Check'}
            </Button>
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/50 p-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {result && (
        <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1">
              <div className="text-xs text-zinc-400">Flow State</div>
              <div className="text-lg font-semibold text-zinc-100">
                {result.FlowState}
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-xs text-zinc-400">Dominant Flow</div>
              <div className="text-lg font-semibold text-zinc-100">
                {result.DominantFlow}
              </div>
            </div>
          </div>

          <div className="space-y-1">
            <div className="text-xs text-zinc-400">Score</div>
            <div className={`text-2xl font-bold ${
              result.Score > 0 ? 'text-green-400' : 
              result.Score < 0 ? 'text-red-400' : 
              'text-zinc-300'
            }`}>
              {result.Score > 0 ? '+' : ''}{result.Score.toFixed(2)}
            </div>
          </div>

          <div className="pt-2 border-t border-zinc-800 space-y-2 text-xs">
            <div className="flex justify-between">
              <span className="text-zinc-400">Alignment</span>
              <span className="text-zinc-100">{result.alignment}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Transmission</span>
              <span className={result.transmission ? 'text-green-400' : 'text-zinc-500'}>
                {result.transmission ? '✓' : '✗'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Persistence</span>
              <span className={result.persistence ? 'text-green-400' : 'text-zinc-500'}>
                {result.persistence ? '✓' : '✗'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Absorption</span>
              <span className={result.absorption ? 'text-amber-400' : 'text-zinc-500'}>
                {result.absorption ? '✓' : '✗'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Vol Spike</span>
              <span className={result.vol_spike ? 'text-red-400' : 'text-zinc-500'}>
                {result.vol_spike ? '✓' : '✗'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Conflict</span>
              <span className={result.conflict ? 'text-orange-400' : 'text-zinc-500'}>
                {result.conflict ? '✓' : '✗'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-400">Assets Analyzed</span>
              <span className="text-zinc-100">{result.assets_count}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
