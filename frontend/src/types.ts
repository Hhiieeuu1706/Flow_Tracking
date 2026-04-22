export type AssetSymbol = 'US30' | 'USTEC' | 'US500' | 'XAUUSD' | 'BTCUSD' | 'DXY' | 'UST10Y' | 'VIX'

export type FlowType = 'FORCE' | 'SQUEEZE' | 'MIXED' | 'OTHER' | 'EVENT'
export type FlowDirection = 'UP' | 'DOWN' | 'FLAT'

export type FlowObject = {
  asset: string
  date: string // YYYY-MM-DD (MT5 server day)
  flow: { type: FlowType; strength: number | null }
  direction: FlowDirection
  note: string
  state: 'Continuation' | 'Absorption' | 'Compression' | null
}

export type DayMeta = {
  date: string // YYYY-MM-DD
  strongest: AssetSymbol | null
  weakest: AssetSymbol | null
  tradeability: 'HIGH' | 'MEDIUM' | 'LOW' | null
  pullback: 'SHALLOW' | 'DEEP' | null
}

export type LwcBar = { time: number; open: number; high: number; low: number; close: number }

export type Session = {
  asset: string
  date: string
  startTime: number
  endTime: number
  bars: LwcBar[]
  flowScore?: number
  regime?: string
}

export type LogicalRange = { from: number; to: number } | null

