/** 输出配置详情工作台：展示完整写入参数与版本数据时间线。 */
import { useCallback, useEffect, useState } from 'react'

import { request } from '@/api/client'
import { Pagination, StatusBadge, formatCell } from '@/components/common'

type VersionRow = Record<string, string | number | boolean | null | Array<Record<string, unknown>>>
type EntryRow = Record<string, string | number | boolean | null>

const PARAM_FIELDS = ['目标地址', '写入模式', '批处理大小', '刷新间隔', '重试策略']
const VERSION_COLUMNS = ['版本号', '动作', '来源', '状态', '处理结论', '最后成功批次', '成功写入次数', '创建时间']

export default function SinkVersionsPanel({ entryId }: { entryId: number }) {
  const [entry, setEntry] = useState<EntryRow | null>(null)
  const [versions, setVersions] = useState<VersionRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [errorMessage, setErrorMessage] = useState('')
  const size = 5

  const load = useCallback(async () => {
    setErrorMessage('')
    try {
      const [entryResp, versionResp] = await Promise.all([
        request(`/api/sink/${entryId}`),
        request(`/api/sink/${entryId}/versions?page=${page}&size=${size}`),
      ])
      if (!entryResp.ok || !versionResp.ok) throw new Error('详情工作台数据读取失败')
      setEntry(await entryResp.json())
      const payload = await versionResp.json()
      setVersions(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '详情工作台数据读取失败')
    }
  }, [entryId, page])

  useEffect(() => {
    void load()
  }, [load])

  if (errorMessage) {
    return <p className="error-text">{errorMessage}</p>
  }

  return (
    <div className="workbench">
      <section className="workbench-section">
        <h4>当前输出配置（完整写入参数）</h4>
        {entry && (
          <dl className="detail-grid">
            <div>
              <dt>配置编号</dt>
              <dd>{formatCell(entry['配置编号'])}</dd>
            </div>
            <div>
              <dt>当前状态</dt>
              <dd>
                <StatusBadge status={String(entry.status ?? '')} />
              </dd>
            </div>
            <div>
              <dt>关闭状态</dt>
              <dd>{entry['关闭状态'] ? '已关闭（终态）' : '未关闭'}</dd>
            </div>
            {PARAM_FIELDS.map((field) => (
              <div key={field}>
                <dt>{field}</dt>
                <dd>{formatCell(entry[field])}</dd>
              </div>
            ))}
            <div>
              <dt>最后成功批次</dt>
              <dd>{formatCell(entry['最后成功批次'])}</dd>
            </div>
            <div>
              <dt>成功写入次数</dt>
              <dd>{formatCell(entry['成功写入次数'])}</dd>
            </div>
          </dl>
        )}
      </section>

      <section className="workbench-section">
        <h4>输出配置版本数据（只追加，历史参数可追溯）</h4>
        <table className="data-table">
          <thead>
            <tr>
              {VERSION_COLUMNS.map((column) => <th key={column}>{column}</th>)}
            </tr>
          </thead>
          <tbody>
            {versions.map((row) => (
              <tr key={String(row.id)}>
                {VERSION_COLUMNS.map((column) => (
                  <td key={column}>
                    {column === '状态' ? <StatusBadge status={String(row[column] ?? '')} /> : formatCell(row[column])}
                  </td>
                ))}
              </tr>
            ))}
            {versions.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={VERSION_COLUMNS.length}>暂无版本数据</td>
              </tr>
            )}
          </tbody>
        </table>
        <Pagination page={page} size={size} total={total} onPageChange={setPage} />
      </section>
    </div>
  )
}
