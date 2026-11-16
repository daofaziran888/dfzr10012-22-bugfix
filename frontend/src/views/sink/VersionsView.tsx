/** 输出配置版本数据查询页：按配置编号、关闭状态、处理结论定位版本，分页结果稳定。 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { request } from '@/api/client'
import { Pagination, StatusBadge, formatCell } from '@/components/common'

type VersionRow = Record<string, string | number | boolean | null>

const columns = [
  '配置编号',
  '版本号',
  '动作',
  '来源',
  '状态',
  '关闭状态',
  '目标地址',
  '写入模式',
  '批处理大小',
  '最后成功批次',
  '成功写入次数',
  '处理结论',
  '创建时间',
]
const statusOptions = ['草稿', '已启用', '已暂停', '已关闭']
const PAGE_SIZE = 10

export default function SinkVersionsView() {
  const [rows, setRows] = useState<VersionRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [filters, setFilters] = useState<Record<string, string>>({})
  const [errorMessage, setErrorMessage] = useState('')

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams({ ...filters, page: String(page), size: String(PAGE_SIZE) }).toString()
    try {
      const response = await request(`/api/sink/versions?${query}`)
      if (!response.ok) throw new Error('输出配置版本数据读取失败')
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '输出配置版本数据读取失败')
    }
  }, [filters, page])

  useEffect(() => {
    void reload()
  }, [reload])

  return (
    <section className="page" data-module="sink-versions">
      <header className="page-head">
        <div>
          <h2>输出配置版本数据</h2>
          <p className="page-desc">
            版本数据只追加不改写，保留关闭状态、完整写入参数与最后成功批次；关闭回执与写入成功指标的处理结论在此可核对。
          </p>
        </div>
        <div className="page-actions">
          <Link className="btn" to="/sink">返回输出列表页</Link>
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
            value={filters.keyword ?? ''}
            placeholder="按配置编号检索，如 SINK-0002"
            onChange={(event) => setFilters((prev) => ({ ...prev, keyword: event.target.value }))}
          />
        </label>
        <label className="filter-item">
          <span>状态</span>
          <select
            value={filters.status ?? ''}
            onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}
          >
            <option value="">全部状态</option>
            {statusOptions.map((status) => <option key={status} value={status}>{status}</option>)}
          </select>
        </label>
        <label className="filter-item">
          <span>处理结论</span>
          <input
            value={filters.conclusion ?? ''}
            placeholder="如 冲突驳回 / 落库"
            onChange={(event) => setFilters((prev) => ({ ...prev, conclusion: event.target.value }))}
          />
        </label>
        <button className="btn" type="submit">查询</button>
        <button
          className="btn ghost"
          type="button"
          onClick={() => {
            setFilters({})
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
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)} className={row['关闭状态'] ? 'row-closed' : ''}>
              {columns.map((column) => (
                <td key={column}>
                  {column === '状态' ? (
                    <StatusBadge status={String(row[column] ?? '')} />
                  ) : column === '关闭状态' ? (
                    <StatusBadge status={row[column] ? '已关闭' : '未关闭'} />
                  ) : (
                    formatCell(row[column])
                  )}
                </td>
              ))}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length}>未检索到匹配的输出配置版本数据</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条版本数据</span>
        <Pagination page={page} size={PAGE_SIZE} total={total} onPageChange={setPage} />
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
