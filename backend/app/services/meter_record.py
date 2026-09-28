"""水表管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store
from app.services.meter_replacement import (
    CURRENT_INSTALL_POSITION_FIELD,
    CURRENT_METER_NO_FIELD,
    NEW_METER_NO_FIELD,
    REPLACEMENT_FIELDS,
    REPLACEMENT_REGISTERED,
    ReplacementDecision,
    evaluate_replacement,
)

MODULE = "meter_record"
REQUIRED_FIELDS = ["表具编号", "表具类型", "口径规格"]
STATUS_ORDER = ["正常", "待换表", "停走", "倒转", "缺电"]
ACTION_RULES = {"现场抄表": "正常", "换表登记": REPLACEMENT_REGISTERED, "恢复供电": "正常"}
NEGATIVE_ACTIONS = []


def _safe_id(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class MeterRecordService:
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
            rows = [row for row in rows if keyword in str(row.get("表具编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        page_rows = rows[start:start + size]
        return [self._with_replacement_rule(row) for row in page_rows], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        return self._with_replacement_rule(entry)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((_safe_id(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def check_replacement(self, entry_id: int, values: dict[str, Any]) -> tuple[dict[str, Any] | None, ReplacementDecision | None]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, None
        decision = self._evaluate_replacement(entry, values)
        return self._with_replacement_rule(entry, decision), decision

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"贸易结算表 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于水表管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        payload = values or {}
        if action == "换表登记":
            if any(field in entry for field in REPLACEMENT_FIELDS):
                return None, "该贸易结算表已登记换表，不能重复登记"
            decision = self._evaluate_replacement(entry, payload)
            if not decision.valid:
                return None, decision.message
            for field_name in REPLACEMENT_FIELDS:
                if field_name in decision.readings:
                    entry[field_name] = decision.readings[field_name]
                else:
                    entry[field_name] = str(payload.get(field_name) or "").strip()

        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self._with_replacement_rule(entry), f"贸易结算表已{action}"

    def _occupied_meter_nos(self, *, exclude_id: int | None = None) -> set[str]:
        occupied: set[str] = set()
        for row in store.rows(MODULE):
            if exclude_id is not None and _safe_id(row.get("id", 0)) == exclude_id:
                continue
            for field_name in (CURRENT_METER_NO_FIELD, NEW_METER_NO_FIELD):
                value = row.get(field_name)
                if value is not None and str(value).strip():
                    occupied.add(str(value).strip())
        return occupied

    def _evaluate_replacement(self, entry: dict[str, Any], values: dict[str, Any]) -> ReplacementDecision:
        entry_id = _safe_id(entry.get("id", 0))
        return evaluate_replacement(
            values,
            current_meter_no=entry.get(CURRENT_METER_NO_FIELD),
            current_install_position=entry.get(CURRENT_INSTALL_POSITION_FIELD),
            occupied_meter_nos=self._occupied_meter_nos(exclude_id=entry_id),
        )

    def _with_replacement_rule(
        self,
        entry: dict[str, Any],
        decision: ReplacementDecision | None = None,
    ) -> dict[str, Any]:
        result = dict(entry)
        has_replacement_values = any(field in entry for field in REPLACEMENT_FIELDS)
        if has_replacement_values or decision is not None:
            if decision is None:
                decision = self._evaluate_replacement(entry, entry)
            result["换表规则"] = decision.as_dict()
        return result
