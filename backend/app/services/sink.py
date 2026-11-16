"""流数据输出端业务规则：状态流转、字段校验与筛选口径都收在这里。

修复点：
- 旧实现把动作映射成前置状态并直接写回，导致「启用→草稿、暂停→已启用、
  关闭→已暂停」的状态回退；这里改为前置条件 + 目标状态的显式状态机；
- 关闭是终态：已关闭输出不能重新启用/暂停，重复关闭只生效一次；
- 每次流转都由 sink_version 固化一版完整写入参数，关闭在同一事务内落库；
- 列表筛选与分页只读，顺序稳定，检索结果不受动作执行影响。
"""
from __future__ import annotations

from typing import Any

from app.services import sink_version
from app.store import store

MODULE = "sink"
REQUIRED_FIELDS = ["配置编号", "输出类型", "目标地址"]
STATUS_ORDER = ["草稿", "已启用", "已暂停", "已关闭"]
CLOSED_STATUS = "已关闭"

# 动作 -> (允许的前置状态, 目标状态)。关闭是终态，不在任何动作的前置状态里。
ACTION_RULES: dict[str, tuple[str, str]] = {
    "启用输出": ("草稿", "已启用"),
    "暂停输出": ("已启用", "已暂停"),
    "关闭输出": ("已暂停", "已关闭"),
}
NEGATIVE_ACTIONS = []


class SinkService:
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
            rows = [row for row in rows if keyword in str(row.get("配置编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def find_by_code(self, config_code: str) -> dict[str, Any] | None:
        """按配置编号（如 SINK-0002）定位输出配置，供跨流程链路回写使用。"""
        code = str(config_code or "").strip()
        if not code:
            return None
        for row in store.rows(MODULE):
            if str(row.get("配置编号", "")).strip() == code:
                return row
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 完整写入参数随登记一起落库，缺省字段给出明确默认值，杜绝后续流转丢字段。
        entry["写入模式"] = values.get("写入模式") or "append"
        entry["批处理大小"] = values.get("批处理大小") or 100
        entry["刷新间隔"] = values.get("刷新间隔") or "10s"
        entry["重试策略"] = values.get("重试策略") or "失败重试3次"
        entry["配置状态"] = STATUS_ORDER[0]
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["关闭状态"] = False
        entry["最后成功批次"] = None
        entry["成功写入次数"] = 0
        rows.append(entry)
        sink_version.ensure_baseline_versions()
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"输出配置 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于流数据输出端可执行范围"

        # 终态护栏：已关闭输出不能重新启用，任何后续流转都拒绝；
        # 唯独重复关闭走幂等路径，返回同一份终态版本，不重复生效、不新增版本。
        if entry.get("status") == CLOSED_STATUS:
            if action == "关闭输出":
                _version, message, _applied = sink_version.close_sink(entry)
                return entry, message
            return None, "输出配置已关闭，关闭为终态，不能重新启用或再次流转"

        precondition, target = ACTION_RULES[action]
        current = entry.get("status")
        if current != precondition:
            return None, f"输出配置当前为「{current}」，仅「{precondition}」状态可执行{action}"
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        if action == "关闭输出":
            # 终态与完整写入参数在 sink_version 内同事务落库，并发关闭只接受一个结果。
            version, message, _applied = sink_version.close_sink(entry)
            if version is None:
                return None, message
            return entry, message

        entry["status"] = target
        entry["配置状态"] = target
        entry["pending"] = target != CLOSED_STATUS
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        entry["关闭状态"] = False
        version = sink_version.append_transition_version(
            entry,
            action=action,
            conclusion=f"已{action}，目标状态「{target}」与完整写入参数已归档",
        )
        entry["最近版本号"] = version["版本号"]
        return entry, f"输出配置已{action}"
