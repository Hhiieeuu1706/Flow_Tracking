import { createChart, type IChartApi } from 'lightweight-charts'
import * as lwc from 'lightweight-charts'

type AnyChart = any
type AnySeries = any

export type CandlesSeriesAdapter = {
  raw: AnySeries
  setData: (data: Array<any>) => void
  setMarkers: (markers: Array<any>) => void
}

export type ChartAdapter = {
  raw: IChartApi
  createCandlesSeries: (options?: Record<string, unknown>) => CandlesSeriesAdapter
}

function hasAddCandlestickSeries(chart: AnyChart): boolean {
  return typeof chart?.addCandlestickSeries === 'function'
}

function hasAddSeries(chart: AnyChart): boolean {
  return typeof chart?.addSeries === 'function'
}

export function createChartAdapter(container: HTMLElement, options: Record<string, unknown>): ChartAdapter {
  const chart = createChart(container, options as any) as unknown as IChartApi

  function createCandlesSeries(seriesOptions?: Record<string, unknown>): CandlesSeriesAdapter {
    const c: AnyChart = chart as any
    let series: AnySeries

    // v3/v4
    if (hasAddCandlestickSeries(c)) {
      series = c.addCandlestickSeries(seriesOptions || {})
    } else if (hasAddSeries(c)) {
      // v5: chart.addSeries(CandlestickSeries, options)
      // Use runtime detection to avoid hard-binding to a single version.
      const CandlestickSeries = (lwc as any)?.CandlestickSeries
      if (!CandlestickSeries) {
        throw new Error('CandlestickSeries export not found (unexpected lightweight-charts version)')
      }
      series = c.addSeries(CandlestickSeries, seriesOptions || {})
    } else {
      throw new Error('Unsupported lightweight-charts version: cannot add candlestick series')
    }

    function setData(data: Array<any>) {
      series.setData(data)
    }

    function setMarkers(markers: Array<any>) {
      if (typeof series?.setMarkers === 'function') {
        series.setMarkers(markers)
        return
      }
      if (typeof (lwc as any)?.createSeriesMarkers === 'function') {
        ;(lwc as any).createSeriesMarkers(series, markers)
        return
      }
      // No markers API found; ignore.
    }

    return { raw: series, setData, setMarkers }
  }

  return { raw: chart, createCandlesSeries }
}

