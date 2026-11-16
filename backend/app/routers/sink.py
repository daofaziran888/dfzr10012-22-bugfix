"""流数据输出端接口：维护输出配置，覆盖启用输出、暂停输出、关闭输出等动作。

版本数据（输出配置版本数据）独立成组接口，支持按配置编号、状态、处理结论
筛选与分页，关闭状态、完整写入参数与最后成功批次都可核对、可追溯。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services import sink_version
from app.services.sink import SinkService

router = APIRouter(prefix="/api/sink", tags=["流数据输出端"])

service = SinkService()

LIST_FIELDS = ["配置编号", "输出类型", "目标地址", "写入模式", "批处理大小", "刷新间隔", "重试策略", "配置状态"]
STATUSES = ["草稿", "已启用", "已暂停", "已关闭"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按配置编号检索"),
    status: str | None = Query(default=None, description="草稿、已启用、已暂停、已关闭"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按配置编号与状态过滤流数据输出端列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出流数据输出端清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "sink", "total": total, "items": items}


@router.get("/versions", response_model=PageResult[dict])
def list_versions(
    keyword: str | None = Query(default=None, description="按配置编号检索版本数据"),
    status: str | None = Query(default=None, description="按版本状态筛选，如 已关闭"),
    conclusion: str | None = Query(default=None, description="按处理结论关键字筛选"),
    sink_id: int | None = Query(default=None, description="按输出配置内部 id 筛选"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """定位输出配置版本数据：筛选、检索与分页口径稳定，版本只追加不改写顺序。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = sink_version.list_versions(
        sink_id=sink_id,
        keyword=keyword,
        status=status,
        conclusion=conclusion,
        page=page,
        size=size,
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/versions/{version_id}", response_model=dict)
def get_version(version_id: int) -> dict:
    """读取单条输出配置版本数据明细；不存在时给出可读的错误说明。"""
    version = sink_version.get_version(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail=f"输出配置版本数据 {version_id} 不存在")
    return version


@router.get("/{entry_id}/versions", response_model=PageResult[dict])
def list_entry_versions(
    entry_id: int,
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """单条输出配置的版本时间线：详情工作台据此展示历史快照与关闭终态。"""
    if service.get_entry(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"输出配置 {entry_id} 不存在或已归档")
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = sink_version.list_versions(sink_id=entry_id, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条输出配置明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"输出配置 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条输出配置，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="输出配置已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条输出配置执行启用输出、暂停输出、关闭输出；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
