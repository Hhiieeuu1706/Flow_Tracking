import { callFlowCheck, type FlowCheckResponse } from './flowCheckApi'
import { useState } from 'react'

interface FlowCheckDisplayProps {
  visible: boolean
}

export function FlowCheckDisplay({ visible }: FlowCheckDisplayProps) {
  const [cutoffDate, setCutoffDate] = useState(
    new Date().toISOString().split('T')[0]
  )
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<FlowCheckResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleRun = async () => {
    setLoading(true)
    setError(null)

    try {
      const res = await callFlowCheck(cutoffDate)
      setResult(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  if (!visible) return null

  return (
    <div className="mt-3 rounded-lg border border-zinc-800 bg-zinc-950 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <input
          type="date"
          value={cutoffDate}
          onChange={(e) => setCutoffDate(e.target.value)}
          className="h-8 flex-1 rounded-md border border-zinc-800 bg-zinc-900 px-2 text-sm"
        />
        <button
          onClick={handleRun}
          disabled={loading}
          className="h-8 px-3 rounded-md border border-zinc-700 bg-zinc-900 text-sm text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
        >
          {loading ? 'Running...' : 'Run Flow Check'}
        </button>
      </div>

      {error && (
        <div className="text-xs text-red-300 bg-red-950/30 p-2 rounded border border-red-800">
          {error}
        </div>
      )}

      {result && (
        <div className="grid grid-cols-6 gap-2 text-xs">
          <div>
            <div className="text-zinc-500">State</div>
            <div className="font-semibold text-zinc-100">{result.FlowState}</div>
          </div>
          <div>
            <div className="text-zinc-500">Flow</div>
            <div className="font-semibold text-zinc-100">{result.DominantFlow}</div>
          </div>
          <div>
            <div className="text-zinc-500">Score</div>
            <div className={`font-semibold ${
              result.Score > 0 ? 'text-green-400' : result.Score < 0 ? 'text-red-400' : 'text-zinc-300'
            }`}>
              {result.Score > 0 ? '+' : ''}{result.Score.toFixed(1)}
            </div>
          </div>
          <div>
            <div className="text-zinc-500">Align</div>
            <div className="font-semibold text-zinc-100">{result.alignment}</div>
          </div>
          <div>
            <div className="text-zinc-500">Trans</div>
            <div className={`font-semibold ${result.transmission ? 'text-green-400' : 'text-zinc-500'}`}>
              {result.transmission ? '✓' : '✗'}
            </div>
          </div>
          <div>
            <div className="text-zinc-500">Abs</div>
            <div className={`font-semibold ${result.absorption ? 'text-amber-400' : 'text-zinc-500'}`}>
              {result.absorption ? '✓' : '✗'}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
