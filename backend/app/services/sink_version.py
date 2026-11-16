"""输出配置版本数据：关闭终态、完整写入参数与最后成功批次的唯一权威来源。

设计要点（对应故障链修复）：

- 每次状态流转都追加一条不可变的版本数据，历史输出参数始终可追溯；
- 关闭输出在同一把锁、同一段事务里完成「终态落库 + 版本写入」，不会出现
  状态回退或只改状态不留快照；
- 并发关闭只接受一个结果：重复关闭幂等返回同一份终态版本，不产生第二条；
- 指标采集（消费侧）只从这里取一份来源明确的版本快照，关闭回执与写入成功
  指标同时到达时，以关闭终态为准，成功写入被驳回且不累加成功次数；
- 版本表以下划线开头挂在内存仓库里，不属于业务模块，不进运营概览。
"""
from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime
from typing import Any

from app.store import store

VERSION_MODULE = "_sink_version"

# 输出端的完整写入参数：版本数据必须整组保留，缺一项都视为快照不完整。
WRITE_FIELDS = ["目标地址", "写入模式", "批处理大小", "刷新间隔", "重试策略"]

CLOSED_STATUS = "已关闭"
SOURCE_BASELINE = "初始化快照"
SOURCE_ACTION = "状态流转"
SOURCE_CLOSE = "关闭回执"
SOURCE_METRIC = "写入成功指标"

CONCLUSION_CLOSED = "关闭终态已落库，写入参数与最后成功批次已固化"
CONCLUSION_SUCCESS = "写入成功已记录，成功写入次数已累加"
CONCLUSION_REJECTED = "冲突驳回：输出配置已是关闭终态，成功写入不予记录"
CONCLUSION_SNAPSHOT = "沿用上一份完整输出配置快照"

# 每个输出配置一把锁：关闭动作与指标回写互斥，保证只有一个终态结论。
_locks: dict[int, threading.RLock] = {}
_locks_guard = threading.Lock()
_table_guard = threading.Lock()


def _entry_lock(sink_id: int) -> threading.RLock:
    with _locks_guard:
        lock = _locks.get(sink_id)
        if lock is None:
            lock = threading.RLock()
            _locks[sink_id] = lock
        return lock


def _version_rows() -> list[dict[str, Any]]:
    return store.rows(VERSION_MODULE)


def _next_version_id() -> int:
    return max((int(row.get("id", 0)) for row in _version_rows()), default=0) + 1


def _next_seq(sink_id: int) -> int:
    return (
        max(
            (int(row.get("版本号", 0)) for row in _version_rows() if int(row.get("sink_id", -1)) == sink_id),
            default=0,
        )
        + 1
    )


def snapshot_sink(entry: dict[str, Any]) -> dict[str, Any]:
    """取一份输出配置的完整深拷贝快照，避免调用方持有可变引用。"""
    snap = {field: deepcopy(entry.get(field)) for field in WRITE_FIELDS}
    snap["最后成功批次"] = deepcopy(entry.get("最后成功批次"))
    snap["成功写入次数"] = int(entry.get("成功写入次数", 0) or 0)
    return snap


def _build_version(
    entry: dict[str, Any],
    *,
    action: str,
    source: str,
    conclusion: str,
) -> dict[str, Any]:
    # id 与版本号在 _append_version 内持表锁统一分配，避免不同输出配置并发建版时撞号。
    version = {
        "sink_id": int(entry["id"]),
        "配置编号": entry.get("配置编号"),
        "动作": action,
        "来源": source,
        "状态": entry.get("status"),
        "关闭状态": entry.get("status") == CLOSED_STATUS,
        "创建时间": datetime.now().isoformat(timespec="seconds"),
        "处理结论": conclusion,
        "处理记录": [],
    }
    version.update(snapshot_sink(entry))
    return version


def _append_version(version: dict[str, Any]) -> dict[str, Any]:
    with _table_guard:
        version["id"] = _next_version_id()
        version["版本号"] = _next_seq(int(version["sink_id"]))
        _version_rows().append(version)
    return deepcopy(version)


def ensure_baseline_versions() -> None:
    """服务启动时为每条输出配置补一份基线版本，保证历史参数从第一版可追溯。"""
    for entry in store.rows("sink"):
        sink_id = int(entry["id"])
        with _entry_lock(sink_id):
            if any(int(row.get("sink_id", -1)) == sink_id for row in _version_rows()):
                continue
            baseline = _build_version(
                entry,
                action="基线归档",
                source=SOURCE_BASELINE,
                conclusion="输出配置基线快照已留存",
            )
            _append_version(baseline)


def latest_version(sink_id: int) -> dict[str, Any] | None:
    """返回某条输出配置当前权威版本的深拷贝；没有版本时返回 None，由调用方走快照兜底。"""
    with _table_guard:
        matched = [row for row in _version_rows() if int(row.get("sink_id", -1)) == sink_id]
    if not matched:
        return None
    return deepcopy(max(matched, key=lambda row: int(row.get("id", 0))))


def list_versions(
    *,
    sink_id: int | None = None,
    keyword: str | None = None,
    status: str | None = None,
    conclusion: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """按配置编号、状态、处理结论筛选版本数据；只追加不删除，分页顺序保持稳定。"""
    with _table_guard:
        rows = [deepcopy(row) for row in _version_rows()]
    if sink_id is not None:
        rows = [row for row in rows if int(row.get("sink_id", -1)) == sink_id]
    if keyword:
        rows = [row for row in rows if keyword in str(row.get("配置编号", ""))]
    if status:
        rows = [row for row in rows if row.get("状态") == status]
    if conclusion:
        rows = [row for row in rows if conclusion in str(row.get("处理结论", ""))]
    rows.sort(key=lambda row: int(row.get("id", 0)))
    total = len(rows)
    start = max(page - 1, 0) * size
    return rows[start:start + size], total


def get_version(version_id: int) -> dict[str, Any] | None:
    with _table_guard:
        for row in _version_rows():
            if int(row.get("id", 0)) == version_id:
                return deepcopy(row)
    return None


def append_transition_version(entry: dict[str, Any], *, action: str, conclusion: str) -> dict[str, Any]:
    """启用/暂停等非终态流转归档一版，写入参数原样固化。"""
    sink_id = int(entry["id"])
    with _entry_lock(sink_id):
        version = _build_version(entry, action=action, source=SOURCE_ACTION, conclusion=conclusion)
        return _append_version(version)


def close_sink(entry: dict[str, Any]) -> tuple[dict[str, Any] | None, str, bool]:
    """关闭输出的唯一入口。

    返回 ``(版本数据, 消息, 是否本次真正落库)``：
    终态与写入参数在同一把锁内一起落库；重复关闭幂等返回同一份终态版本，
    并发关闭只有第一个调用落库，其余调用拿到同一个结果。
    """
    sink_id = int(entry["id"])
    lock = _entry_lock(sink_id)
    with lock:
        if entry.get("status") == CLOSED_STATUS:
            terminal = latest_version(sink_id)
            if terminal is None:
                # 理论上不会发生：终态一定伴随版本数据。没有就现场补一份，保证可核对。
                terminal = _append_version(
                    _build_version(entry, action="关闭输出", source=SOURCE_CLOSE, conclusion=CONCLUSION_CLOSED)
                )
            return terminal, "输出配置已处于关闭终态，重复关闭只生效一次，本次未重复落库", False

        # 先基于关闭前快照在局部构造终态条目与版本，任何一步失败都不动共享数据。
        before = {
            "status": entry.get("status"),
            "pending": entry.get("pending"),
            "abnormal": entry.get("abnormal"),
            "配置状态": entry.get("配置状态"),
            "关闭状态": entry.get("关闭状态"),
            "最后成功批次": entry.get("最后成功批次"),
            "成功写入次数": entry.get("成功写入次数", 0),
        }
        stored: dict[str, Any] | None = None
        try:
            snapshot = snapshot_sink(entry)
            terminal_entry = dict(entry)
            terminal_entry["status"] = CLOSED_STATUS
            terminal_entry["pending"] = False
            terminal_entry["abnormal"] = False
            terminal_entry["配置状态"] = CLOSED_STATUS
            terminal_entry["关闭状态"] = True
            terminal_entry["最后成功批次"] = snapshot["最后成功批次"]
            terminal_entry["成功写入次数"] = snapshot["成功写入次数"]
            version = _build_version(
                terminal_entry,
                action="关闭输出",
                source=SOURCE_CLOSE,
                conclusion=CONCLUSION_CLOSED,
            )
            # 版本先落库；条目随后更新，任一步失败都整体回滚，不留半份终态。
            stored = _append_version(version)
            entry.update(
                {
                    "status": CLOSED_STATUS,
                    "pending": False,
                    "abnormal": False,
                    "配置状态": CLOSED_STATUS,
                    "关闭状态": True,
                    "最后成功批次": snapshot["最后成功批次"],
                    "成功写入次数": snapshot["成功写入次数"],
                }
            )
        except Exception as exc:  # pragma: no cover - 事务兜底
            if stored is not None:
                with _table_guard:
                    table = _version_rows()
                    for idx in range(len(table) - 1, -1, -1):
                        if int(table[idx].get("id", 0)) == int(stored["id"]):
                            table.pop(idx)
                            break
            entry.update(before)
            return None, f"关闭输出落库失败，已保留上一份完整快照：{exc}", False
        return stored, "输出配置已关闭输出，终态与完整写入参数同事务落库", True


def resolve_write_result(
    entry: dict[str, Any],
    *,
    batch_no: str | None,
) -> tuple[dict[str, Any], bool, str]:
    """消费侧（指标采集）上报写入结果时的唯一裁决入口。

    关闭回执与写入成功指标只认同一份版本数据：版本已是关闭终态时，成功写入
    被驳回、成功次数不增加，处理结论回写到同一版本；仍在运行时才累加成功次数。
    """
    sink_id = int(entry["id"])
    with _entry_lock(sink_id):
        version = latest_version(sink_id)
        if version is None:
            # 版本链路异常时不阻断业务：沿用上一份完整快照兜底。
            fallback = snapshot_sink(entry)
            fallback.update(
                {
                    "id": None,
                    "sink_id": sink_id,
                    "配置编号": entry.get("配置编号"),
                    "状态": entry.get("status"),
                    "关闭状态": entry.get("status") == CLOSED_STATUS,
                    "处理结论": CONCLUSION_SNAPSHOT,
                    "处理记录": [],
                }
            )
            version = fallback

        now = datetime.now().isoformat(timespec="seconds")
        if version.get("关闭状态") or entry.get("status") == CLOSED_STATUS:
            note = CONCLUSION_REJECTED
            version["处理结论"] = note
            version.setdefault("处理记录", []).append(
                {"来源": SOURCE_METRIC, "批次号": batch_no, "结论": note, "时间": now}
            )
            _write_back(version)
            return deepcopy(version), False, note

        accepted_batch = batch_no or entry.get("最后成功批次")
        entry["最后成功批次"] = accepted_batch
        entry["成功写入次数"] = int(entry.get("成功写入次数", 0) or 0) + 1
        version["最后成功批次"] = accepted_batch
        version["成功写入次数"] = int(version.get("成功写入次数", 0) or 0) + 1
        version["处理结论"] = CONCLUSION_SUCCESS
        version.setdefault("处理记录", []).append(
            {"来源": SOURCE_METRIC, "批次号": accepted_batch, "结论": CONCLUSION_SUCCESS, "时间": now}
        )
        _write_back(version)
        return deepcopy(version), True, CONCLUSION_SUCCESS


def _write_back(version: dict[str, Any]) -> None:
    """把消费侧处理结论同步回写同一份版本数据（基线兜底版本没有主键时只回写条目）。"""
    version_id = version.get("id")
    if version_id is None:
        return
    with _table_guard:
        for row in _version_rows():
            if int(row.get("id", 0)) == int(version_id):
                row["最后成功批次"] = version.get("最后成功批次")
                row["成功写入次数"] = version.get("成功写入次数")
                row["处理结论"] = version.get("处理结论")
                row["处理记录"] = deepcopy(version.get("处理记录", []))
                return


# 仓库初始化后立即补齐基线版本，重复执行幂等。
ensure_baseline_versions()
