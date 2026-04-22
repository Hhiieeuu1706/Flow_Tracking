import type { LwcBar, Session } from '../types'

// MT5 server-time visualization offset (hours from UTC).
// Adjusted to -7 to make the session start at 07:00 AM.
export const MT5_SERVER_UTC_OFFSET_HOURS = -7

export function yyyyMmDdFromUnixSeconds(sec: number) {
  // bar.time is unix seconds (UTC). Shift to server-time, then read by UTC getters.
  const d = new Date((sec + MT5_SERVER_UTC_OFFSET_HOURS * 3600) * 1000)
  const y = d.getUTCFullYear()
  const m = String(d.getUTCMonth() + 1).padStart(2, '0')
  const day = String(d.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function buildSessions(asset: string, bars: LwcBar[]): Session[] {
  const sessions: Session[] = []
  let current: Session | null = null

  for (const bar of bars) {
    const date = yyyyMmDdFromUnixSeconds(bar.time)
    const isNewDate = current && current.date !== date

    // Always start a new session if the date changes (based on our -7h offset).
    // Gaps (like weekends) will now correctly merge into the "logical" day 
    // until the clock hits 07:00 AM.
    if (!current || isNewDate) {
      if (current) sessions.push(current)
      current = {
        asset,
        date,
        startTime: bar.time,
        endTime: bar.time,
        bars: [bar],
      }
    } else {
      current.endTime = bar.time
      current.bars.push(bar)
    }
  }

  if (current) sessions.push(current)
  return sessions
}

export function buildChartDataWithGaps(sessions: Session[]) {
  const data: Array<LwcBar | { time: number }> = []
  for (let i = 0; i < sessions.length; i++) {
    const s = sessions[i]
    for (const b of s.bars) data.push(b)
    const next = sessions[i + 1]
    if (next) {
      // lightweight-charts whitespace item (no OHLC) to create visual break.
      data.push({ time: s.endTime + 1 })
    }
  }
  return data
}

