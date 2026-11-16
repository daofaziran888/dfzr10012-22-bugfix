import { useCallback, useEffect, useMemo, useState } from 'react'

import { readErrorMessage, request } from '@/api/client'
import { Drawer, Pagination, StatusBadge, formatCell } from '@/components/common'

import SinkVersionsPanel from './SinkVersionsPanel'

const ENDPOINT = '/api/sink'
const columns = [
  "配置编号",
  "输出类型",
  "目标地址",
  "写入模式",
  "批处理大小",
  "刷新间隔",
  "重试策略",
  "配置状态"
]
// 动作 -> 允许执行的前置状态。已关闭为终态，不在任何动作的前置状态里。
const ACTION_PRECONDITIONS: Record<string, string[]> = {
  启用输出: ['草稿'],
  暂停输出: ['已启用'],
  关闭输出: ['已暂停'],
}
const statusOptions = ["草稿", "已启用", "已暂停", "已关闭"]
const PAGE_SIZE = 10

type Row = Record<string, string | number | boolean | null>

export default function SinkView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [keyword, setKeyword] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [errorMessage, setErrorMessage] = useState('')
  const [detailId, setDetailId] = useState<number | null>(null)

  const queryString = useMemo(
    () =>
      new URLSearchParams({
        ...(keyword ? { keyword } : {}),
        ...(statusFilter ? { status: statusFilter } : {}),
        page: String(page),
        size: String(PAGE_SIZE),
      }).toString(),
    [keyword, statusFilter, page],
  )

  const reload = useCallback(async () => {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}?${queryString}`)
      if (!response.ok) {
        throw new Error(await readErrorMessage(response, '输出配置列表读取失败'))
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '流数据输出端列表读取失败')
    }
  }, [queryString])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      const payload = await response.json()
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.message || '流数据输出端动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '流数据输出端操作失败')
    }
  }

  return (
    <section className="page" data-module="sink">
      <header className="page-head">
        <div>
          <h2>流数据输出端管理</h2>
          <p className="page-desc">维护流输出的目标地址、写入模式与批处理配置；关闭为终态，关闭状态与完整写入参数同事务固化到版本数据。</p>
        </div>
        <div className="page-actions">
          <a className="btn" href={`${ENDPOINT}/export`}>导出流数据输出端清单</a>
          <a className="btn primary" href="/sink/versions">查看输出配置版本数据</a>
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
          <span>配置编号</span>
          <input
            value={keyword}
            placeholder="按配置编号检索，如 SINK-0002"
            onChange={(event) => setKeyword(event.target.value)}
          />
        </label>
        <label className="filter-item">
          <span>配置状态</span>
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
            const isClosed = currentStatus === '已关闭'
            return (
              <tr key={String(row.id)} className={isClosed ? 'row-closed' : ''}>
                {columns.map((column) => <td key={column}>{formatCell(row[column])}</td>)}
                <td><StatusBadge status={currentStatus} /></td>
                <td className="row-actions">
                  {Object.entries(ACTION_PRECONDITIONS).map(([action, preconditions]) => {
                    const allowed = preconditions.includes(currentStatus)
                    return (
                      <button
                        key={action}
                        className="link"
                        type="button"
                        disabled={!allowed}
                        title={allowed ? action : `仅${preconditions.join('、')}状态可执行${action}`}
                        onClick={() => void runAction(action, row)}
                      >
                        {action}
                      </button>
                    )
                  })}
                  <button className="link" type="button" onClick={() => setDetailId(Number(row.id))}>
                    详情工作台
                  </button>
                </td>
              </tr>
            )
          })}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 2}>暂无匹配的流数据输出端数据</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条流数据输出端记录</span>
        <Pagination page={page} size={PAGE_SIZE} total={total} onPageChange={setPage} />
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>

      {detailId !== null && (
        <Drawer title={`输出配置详情工作台 #${detailId}`} onClose={() => setDetailId(null)}>
          <SinkVersionsPanel entryId={detailId} />
        </Drawer>
      )}
    </section>
  )
}
