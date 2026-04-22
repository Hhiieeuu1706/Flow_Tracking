import type { DayMeta, FlowDirection, FlowObject, FlowType } from '../types'
import { db } from '../db/db'

// Flow is shared by day across all symbols.
export function flowKey(asset: string, date: string) {
  void asset
  return `flow_${date}`
}

function normalizeFlowType(t: any): FlowType {
  if (t === 'FORCE' || t === 'SQUEEZE' || t === 'MIXED' || t === 'OTHER') return t
  // Backward compat: previous app variants
  if (t === 'GAMMA' || t === 'FORCED' || t === 'FLOW') return 'FORCE'
  if (t === 'NONE') return 'OTHER'
  return 'OTHER'
}

function normalizeDirection(d: any): FlowDirection {
  if (d === 'UP' || d === 'DOWN' || d === 'FLAT') return d
  return 'FLAT'
}

export async function loadFlow(asset: string, date: string): Promise<FlowObject | null> {
  const id = flowKey(asset, date)
  let row = await db.flows.get(id)

  // Backward-compat: if old per-asset key exists, read it.
  if (!row) {
    row = await db.flows.get(`${asset}_${date}`)
  }
  if (!row) return null
  const rawStrength = (row as any).strength
  const normalizedStrength = rawStrength == null ? null : Number(rawStrength)
  const strength = Number.isFinite(normalizedStrength) ? normalizedStrength : null
  const normalized = {
    asset: row.asset,
    date: row.date,
    flow: { type: normalizeFlowType((row as any).flowType), strength },
    direction: normalizeDirection((row as any).direction),
    note: row.note,
    state: (row as any).state ?? null,
  }

  // Migrate stored type if needed (best-effort)
  const currentType = (row as any).flowType
  if (currentType !== normalized.flow.type) {
    await db.flows.put({ ...(row as any), flowType: normalized.flow.type })
  }
  return normalized
}

export async function loadFlowsBulk(ids: string[]): Promise<Map<string, FlowObject>> {
  // ids are expected to be shared-by-day keys: flow_YYYY-MM-DD
  const rows = await db.flows.bulkGet(ids)
  const map = new Map<string, FlowObject>()
  const assetsFallback = ['DJ30.f', 'USTEC.f', 'US500.f'] as const

  for (let i = 0; i < ids.length; i++) {
    const id = ids[i]
    let row: any = rows[i]

    // If missing, attempt to find a legacy per-asset record and migrate it.
    if (!row && id.startsWith('flow_')) {
      const date = id.slice('flow_'.length)
      for (const a of assetsFallback) {
        // eslint-disable-next-line no-await-in-loop
        const legacy = await db.flows.get(`${a}_${date}`)
        if (legacy) {
          row = legacy as any
          // migrate to shared key for next time
          // eslint-disable-next-line no-await-in-loop
          await db.flows.put({ ...(legacy as any), id, flowType: normalizeFlowType((legacy as any).flowType) })
          break
        }
      }
    }

    if (!row) continue
    const normalizedType = normalizeFlowType(row.flowType)
    if (row.flowType !== normalizedType) {
      // eslint-disable-next-line no-await-in-loop
      await db.flows.put({ ...(row as any), flowType: normalizedType })
    }
    const rawStrength = Number((row as any).strength)
    const normalizedStrength = Number.isFinite(rawStrength) ? rawStrength : 1
    map.set(row.date, {
      asset: row.asset,
      date: row.date,
      flow: { type: normalizedType, strength: normalizedStrength },
      direction: normalizeDirection(row.direction),
      note: row.note,
      state: (row as any).state ?? null,
    })
  }
  return map
}

export async function saveFlow(flow: FlowObject) {
  const id = flowKey(flow.asset, flow.date)
  await db.flows.put({
    id,
    asset: flow.asset,
    date: flow.date,
    flowType: flow.flow.type,
    strength: flow.flow.strength,
    direction: flow.direction,
    note: flow.note,
    state: flow.state,
    updatedAt: Date.now(),
  })
}

export async function resetAllStrengths() {
  const allFlows = await db.flows.toArray()
  for (const flow of allFlows) {
    await db.flows.update(flow.id, { strength: null })
  }
}

export async function getBackupFlowData() {
  return await db.flows.toArray()
}

export async function restoreFlowData(backup: any[]) {
  await db.flows.clear()
  if (backup && backup.length > 0) {
    await db.flows.bulkPut(backup)
  }
}

export async function clearAllFlowData() {
  await db.flows.clear()
}

export async function loadDayMeta(date: string): Promise<DayMeta | null> {
  const row = await db.dayMeta.get(date)
  if (!row) return null
  return {
    date: row.date,
    strongest: row.strongest,
    weakest: row.weakest,
    tradeability: (row as any).tradeability ?? null,
    pullback: (row as any).pullback ?? null,
  }
}

export async function saveDayMeta(meta: DayMeta) {
  await db.dayMeta.put({
    date: meta.date,
    strongest: meta.strongest,
    weakest: meta.weakest,
    tradeability: meta.tradeability ?? null,
    pullback: meta.pullback ?? null,
    updatedAt: Date.now(),
  })
}

export async function loadDayMetaBulk(dates: string[]) {
  const rows = await db.dayMeta.bulkGet(dates)
  const map = new Map<string, DayMeta>()
  for (const row of rows) {
    if (!row) continue
    map.set(row.date, {
      date: row.date,
      strongest: row.strongest,
      weakest: row.weakest,
      tradeability: (row as any).tradeability ?? null,
      pullback: (row as any).pullback ?? null,
    })
  }
  return map
}

function barKey(symbol: string, timeframe: 'H1', time: number) {
  return `${symbol}_${timeframe}_${time}`
}

export async function getBarsFromCache(symbol: string, timeframe: 'H1', fromSec: number, toSec: number) {
  void timeframe
  const rows = await db.bars
    .where('[symbol+time]')
    .between([symbol, fromSec], [symbol, toSec], true, true)
    .toArray()
  return rows.map((r) => ({ time: r.time, open: r.open, high: r.high, low: r.low, close: r.close }))
}

export async function upsertBarsToCache(symbol: string, timeframe: 'H1', bars: Array<{ time: number; open: number; high: number; low: number; close: number }>) {
  const now = Date.now()
  await db.bars.bulkPut(
    bars.map((b) => ({
      key: barKey(symbol, timeframe, b.time),
      symbol,
      timeframe,
      time: b.time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
      updatedAt: now,
    })),
  )
}

export async function getCachedCoverage(symbol: string, timeframe: 'H1', fromSec: number, toSec: number) {
  void timeframe
  const rows = await db.bars
    .where('[symbol+time]')
    .between([symbol, fromSec], [symbol, toSec], true, true)
    .toArray()
  if (rows.length === 0) return { hasAny: false, min: null as number | null, max: null as number | null }
  return { hasAny: true, min: rows[0].time, max: rows[rows.length - 1].time }
}

export async function clearBarsCache() {
  await db.bars.clear()
}

export async function clearAllCaches() {
  await db.bars.clear()
  await db.flows.clear()
  await db.dayMeta.clear()
}

