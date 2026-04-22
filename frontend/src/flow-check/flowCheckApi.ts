export interface FlowCheckResponse {
  FlowState: string
  DominantFlow: string
  Score: number
  alignment: number
  transmission: boolean
  persistence: boolean
  absorption: boolean
  vol_spike: boolean
  conflict: boolean
  Regime: string
  assets_count: number
}

export async function callFlowCheck(cutoffDate: string): Promise<FlowCheckResponse> {
  const params = new URLSearchParams({
    cutoff: cutoffDate,
  })

  const response = await fetch(`/api/flow-check?${params.toString()}`)
  if (!response.ok) {
    const error = await response.json()
    throw new Error(error.error || `HTTP ${response.status}`)
  }

  return response.json()
}
