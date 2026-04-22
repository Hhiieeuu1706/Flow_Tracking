import Dexie, { type Table } from 'dexie'

import type { AssetSymbol, FlowDirection, FlowType } from '../types'

export type FlowRow = {
  id: string // `${asset}_${date}`
  asset: string
  date: string // YYYY-MM-DD (MT5 server day)
  flowType: FlowType
  strength: number | null
  direction: FlowDirection
  note: string
  state: 'Continuation' | 'Absorption' | 'Compression' | null
  updatedAt: number // unix ms
}

export type BarRow = {
  key: string // `${symbol}_H1_${time}`
  symbol: string
  timeframe: 'H1'
  time: number // unix seconds
  open: number
  high: number
  low: number
  close: number
  updatedAt: number // unix ms
}

export type DayMetaRow = {
  date: string // YYYY-MM-DD
  strongest: AssetSymbol | null
  weakest: AssetSymbol | null
  tradeability: 'HIGH' | 'MEDIUM' | 'LOW' | null
  pullback: 'SHALLOW' | 'DEEP' | null
  updatedAt: number
}

export class FlowDb extends Dexie {
  flows!: Table<FlowRow, string>
  bars!: Table<BarRow, string>
  dayMeta!: Table<DayMetaRow, string>

  constructor() {
    super('flow_tracking_db')
    this.version(1).stores({
      flows: '&id, asset, date, updatedAt',
    })
    this.version(2).stores({
      flows: '&id, asset, date, updatedAt',
      bars: '&key, [symbol+time], symbol, timeframe, time, updatedAt',
    })
    this.version(3).stores({
      flows: '&id, asset, date, updatedAt',
      bars: '&key, [symbol+time], symbol, timeframe, time, updatedAt',
      dayMeta: '&date, updatedAt',
    })
    this.version(4).stores({
      flows: '&id, asset, date, updatedAt',
      bars: '&key, [symbol+time], symbol, timeframe, time, updatedAt',
      dayMeta: '&date, updatedAt',
    })
    this.version(7).stores({
      flows: '&id, asset, date, updatedAt',
      bars: '&key, [symbol+time], symbol, timeframe, time, updatedAt',
      dayMeta: '&date, updatedAt',
    })
  }
}

export const db = new FlowDb()

