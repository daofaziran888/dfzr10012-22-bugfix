"""流作业指标采集业务规则：状态流转、字段校验、筛选口径与跨流程结论裁决。

与输出端的联动规则：
- 指标采集上报「写入成功」时，只认 sink_version 中来源明确的同一份输出配置
  版本数据，不能一边标记关闭一边累加成功写入次数；
- 输出配置已关闭（关闭回执先到/同时到）时，成功写入指标被驳回，成功写入次数
  不增加，处理结论回写到同一份版本数据，消费侧保留处理结论；
- 版本链路异常时沿用上一份完整快照，不阻断采集流程。
"""
from __future__ import annotations

from typing import Any

from app.services import sink_version
from app.services.sink import SinkService
from app.store import store

MODULE = "metric"
REQUIRED_FIELDS = ["采集器编号", "作业名称", "指标名称"]
STATUS_ORDER = ["草稿", "采集中", "已暂停", "已关闭"]
CLOSED_STATUS = "已关闭"

# 动作 -> (允许的前置状态, 目标状态)。关闭是终态，不允许再流转。
ACTION_RULES: dict[str, tuple[str, str]] = {
    "启动采集": ("草稿", "采集中"),
    "暂停采集": ("采集中", "已暂停"),
    "关闭采集": ("已暂停", "已关闭"),
}
NEGATIVE_ACTIONS = []


class MetricService:
    def __init__(self) -> None:
        self._sinks = SinkService()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("采集器编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["采集器状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["关联输出配置"] = values.get("关联输出配置")
        entry["成功写入次数"] = 0
        entry["最近处理结论"] = None
        entry["最近参考版本"] = None
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"指标采集器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于流作业指标采集可执行范围"
        if entry.get("status") == CLOSED_STATUS:
            return None, "指标采集器已关闭，关闭为终态，不能重新启动或再次流转"

        precondition, target = ACTION_RULES[action]
        current = entry.get("status")
        if current != precondition:
            return None, f"指标采集器当前为「{current}」，仅「{precondition}」状态可执行{action}"
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        entry["status"] = target
        entry["采集器状态"] = target
        entry["pending"] = target != CLOSED_STATUS
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"指标采集器已{action}"

    # ------------------------------------------------------------------
    # 跨流程链路：写入成功指标 vs 输出配置关闭回执的冲突裁决
    # ------------------------------------------------------------------

    def _resolve_sink(self, entry: dict[str, Any], sink_code: str | None) -> dict[str, Any] | None:
        code = str(sink_code or entry.get("关联输出配置") or "").strip()
        if not code:
            # 兜底：同序号采集器与输出配置对应（METR-0002 <-> SINK-0002）。
            metric_code = str(entry.get("采集器编号", ""))
            digits = "".join(ch for ch in metric_code if ch.isdigit())
            code = f"SINK-{digits}" if digits else ""
        return self._sinks.find_by_code(code) if code else None

    def record_write_result(
        self,
        entry_id: int,
        *,
        sink_code: str | None = None,
        batch_no: str | None = None,
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
        """消费侧处理一次写入结果（关闭回执与成功指标同时到达时的统一入口）。

        返回 ``(采集器, 参考版本, 消息)``。成功被接受才累加成功写入次数；
        关闭终态下的成功指标只保留驳回结论，计数不变。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, None, f"指标采集器 {entry_id} 不存在或已归档"

        sink = self._resolve_sink(entry, sink_code)
        if sink is None:
            return None, None, "未找到关联的输出配置，写入结果无法核对输出配置版本数据"

        # 只使用一个来源明确的版本数据做裁决，结论回写同一份版本。
        version, accepted, message = sink_version.resolve_write_result(
            sink,
            batch_no=str(batch_no).strip() if batch_no is not None else None,
        )

        entry["关联输出配置"] = sink.get("配置编号")
        entry["最近参考版本"] = version.get("id")
        entry["最近处理结论"] = message
        if accepted:
            entry["成功写入次数"] = int(entry.get("成功写入次数", 0) or 0) + 1
        return entry, version, message

    def latest_sink_snapshot(self, entry_id: int) -> dict[str, Any] | None:
        """取关联输出配置的当前权威版本快照（深拷贝），失败时由版本服务走快照兜底。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        sink = self._resolve_sink(entry, None)
        if sink is None:
            return None
        version = sink_version.latest_version(int(sink["id"]))
        if version is not None:
            return version
        snapshot = sink_version.snapshot_sink(sink)
        snapshot["配置编号"] = sink.get("配置编号")
        snapshot["状态"] = sink.get("status")
        snapshot["关闭状态"] = sink.get("status") == sink_version.CLOSED_STATUS
        snapshot["处理结论"] = sink_version.CONCLUSION_SNAPSHOT
        return snapshot
