/** 工作台通用组件：抽屉、分页与状态徽标，供输出列表页和详情工作台复用。 */
import type { ReactNode } from 'react'

const STATUS_TONE: Record<string, string> = {
  已关闭: 'badge-closed',
  已暂停: 'badge-paused',
  已启用: 'badge-active',
  采集中: 'badge-active',
  草稿: 'badge-draft',
}

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const value = String(status ?? '—')
  return <span className={`status-badge ${STATUS_TONE[value] ?? 'badge-draft'}`}>{value}</span>
}

export function Drawer({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: ReactNode
}) {
  return (
    <div className="drawer-mask" role="presentation" onClick={onClose}>
      <aside className="drawer" role="dialog" aria-label={title} onClick={(event) => event.stopPropagation()}>
        <header className="drawer-head">
          <h3>{title}</h3>
          <button className="btn ghost" type="button" onClick={onClose}>关闭</button>
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  )
}

export function Pagination({
  page,
  size,
  total,
  onPageChange,
}: {
  page: number
  size: number
  total: number
  onPageChange: (page: number) => void
}) {
  const pageCount = Math.max(1, Math.ceil(total / size))
  return (
    <div className="pagination">
      <button className="btn" type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        上一页
      </button>
      <span>
        第 {page} / {pageCount} 页
      </span>
      <button
        className="btn"
        type="button"
        disabled={page >= pageCount}
        onClick={() => onPageChange(page + 1)}
      >
        下一页
      </button>
    </div>
  )
}

export function formatCell(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}
