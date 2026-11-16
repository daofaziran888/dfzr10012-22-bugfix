import { useCallback, useEffect, useMemo, useState } from 'react'

import { readErrorMessage, request } from '@/api/client'
import { Pagination, StatusBadge, formatCell } from '@/components/common'

const ENDPOINT = '/api/metric'
const columns = [
  "采集器编号",
  "作业名称",
  "指标名称",
  "采集间隔",
  "聚合方式",
  "保留天数",
  "最近采集",
  "采集器状态",
  "关联输出配置",
  "成功写入次数",
  "最近处理结论"
]
// 动作 -> 允许执行的前置状态。已关闭为终态。
const ACTION_PRECONDITIONS: Record<string, string[]> = {
  启动采集: ['草稿'],
  暂停采集: ['采集中'],
  关闭采集: ['已暂停'],
}
const statusOptions = ["草稿", "采集中", "已暂停", "已关闭"]
const PAGE_SIZE = 10

type Row = Record<string, string | number | boolean | null>

export default function MetricView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [notice, setNotice] = useState('')
  const filterFields = useMemo(() => ["采集器编号", "作业名称", "指标名称"], [])

  const queryString = useMemo(() => {
    const params: Record<string, string> = { page: String(page), size: String(PAGE_SIZE) }
    if (keyword) params.keyword = keyword
    if (statusFilter) params.status = statusFilter
    return new URLSearchParams(params).toString()
  }, [keyword, statusFilter, page])

  const reload = useCallback(async () => {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}?${queryString}`)
      if (!response.ok) {
        throw new Error(await readErrorMessage(response, '指标采集器列表读取失败'))
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '流作业指标采集列表读取失败')
    }
  }, [queryString])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message || '流作业指标采集动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '流作业指标采集操作失败')
    }
  }

  async function reportWriteResult(row: Row) {
    setErrorMessage('')
    setNotice('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/write-results`, {
        method: 'POST',
        body: JSON.stringify({ values: { sink_code: row['关联输出配置'] } }),
      })
      const payload = await response.json()
      // 关闭终态下后端返回 ok=false 的冲突驳回，这是有效处理结论，不算接口异常。
      if (!response.ok) {
        throw new Error(payload.message || '写入结果上报失败')
      }
      setNotice(payload.message || '写入结果已处理')
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '写入结果上报失败')
    }
  }

  return (
    <section className="page" data-module="metric">
      <header className="page-head">
        <div>
          <h2>流作业指标采集管理</h2>
          <p className="page-desc">
            写入成功指标只认一份来源明确的输出配置版本数据：关联输出已关闭时成功写入被驳回且不计数，处理结论随版本数据留存。
          </p>
        </div>
        <div className="page-actions">
          <a className="btn" href={`${ENDPOINT}/export`}>导出流作业指标采集清单</a>
        </div>
      </header>

      <form
        className="filter-bar"
        onSubmit={(event) => {
          event.preventDefault()
          setPage(1)
          void reload()
        }}
      >
        <label className="filter-item">
          <span>{filterFields[0]}</span>
          <input
            value={keyword}
            placeholder={`按${filterFields[0]}检索`}
            onChange={(event) => setKeyword(event.target.value)}
          />
        </label>
        <label className="filter-item">
          <span>采集器状态</span>
          <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1) }}>
            <option value="">全部状态</option>
            {statusOptions.map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
        </label>
        <button className="btn" type="submit">查询</button>
        <button
          className="btn ghost"
          type="button"
          onClick={() => {
            setKeyword('')
            setStatusFilter('')
            setPage(1)
          }}
        >
          重置条件
        </button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>状态</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const currentStatus = String(row.status ?? '')
            return (
              <tr key={String(row.id)}>
                {columns.map((column) => (
                  <td key={column} className={column === '最近处理结论' && String(row[column] ?? '').includes('驳回') ? 'cell-conflict' : ''}>
                    {formatCell(row[column])}
                  </td>
                ))}
                <td><StatusBadge status={currentStatus} /></td>
                <td className="row-actions">
                  {Object.entries(ACTION_PRECONDITIONS).map(([action, preconditions]) => (
                    <button
                      key={action}
                      className="link"
                      type="button"
                      disabled={!preconditions.includes(currentStatus)}
                      title={`仅${preconditions.join('、')}状态可执行${action}`}
                      onClick={() => void runAction(action, row)}
                    >
                      {action}
                    </button>
                  ))}
                  <button className="link" type="button" onClick={() => void reportWriteResult(row)}>
                    上报写入成功
                  </button>
                </td>
              </tr>
            )
          })}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 2}>暂无匹配的流作业指标采集数据</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条流作业指标采集记录</span>
        <Pagination page={page} size={PAGE_SIZE} total={total} onPageChange={setPage} />
        {notice && <span className="notice-text">{notice}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
