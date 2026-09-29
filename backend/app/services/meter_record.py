"""水表管理业务规则：状态流转、字段校验与换表判断都收在这里。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.services.meter_rules import (
    CURRENT_READING,
    NEW_LOCATION,
    NEW_METER_NO,
    NEW_START_READING,
    OLD_LOCATION,
    OLD_METER_NO,
    OLD_STOP_READING,
    PREVIOUS_READING,
    REPLACEMENT_FIELDS,
    clean_text,
    evaluate_meter_replacement,
)
from app.store import store

MODULE = "meter_record"
REQUIRED_FIELDS = ["表具编号", "表具类型", "口径规格"]
STATUS_ORDER = ["正常", "待换表", "停走", "倒转", "缺电"]
ACTION_RULES = {"现场抄表": "正常", "换表登记": "待换表", "恢复供电": "正常"}
NEGATIVE_ACTIONS = []
REPLACE_ACTION = "换表登记"


class MeterRecordService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = [self._with_rule(row) for row in store.rows(MODULE)]
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("表具编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._with_rule(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not clean_text(values.get(field))]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field, value in values.items():
            if field in REQUIRED_FIELDS or clean_text(value):
                entry[field] = value
        for field in REQUIRED_FIELDS:
            entry.setdefault(field, values.get(field))
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return self._with_rule(entry), []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"贸易结算表 {entry_id} 不存在或已归档", None
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于水表管理可执行范围", None
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里", None

        payload = values or {}
        rule = None
        if action == REPLACE_ACTION:
            rule = evaluate_meter_replacement(
                entry,
                payload,
                explicit_fields=payload.keys(),
                existing_meter_numbers=self._existing_meter_numbers(entry_id),
                has_replacement_input=True,
            )
            if not rule["allowed"]:
                missing = [f"缺少{field}" for field in rule["missingFields"]]
                detail = "；".join(rule["issues"] + missing) or "换表信息未补录完整"
                return None, f"换表登记未通过：{detail}", rule
            self._apply_replacement(entry, payload, rule)

        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return self._with_rule(entry), f"贸易结算表已{action}", rule

    def _existing_meter_numbers(self, entry_id: int) -> set[str]:
        numbers: set[str] = set()
        for row in store.rows(MODULE):
            if int(row.get("id", 0)) == entry_id:
                continue
            for field in ("表具编号", NEW_METER_NO, OLD_METER_NO):
                number = clean_text(row.get(field))
                if number:
                    numbers.add(number)
        return numbers

    def _apply_replacement(
        self,
        entry: dict[str, Any],
        payload: dict[str, Any],
        rule: dict[str, Any],
    ) -> None:
        fields = rule["fields"]
        canonical_values = {
            OLD_METER_NO: fields[OLD_METER_NO]["value"],
            NEW_METER_NO: fields[NEW_METER_NO]["value"],
            OLD_STOP_READING: fields[OLD_STOP_READING]["value"],
            NEW_START_READING: fields[NEW_START_READING]["value"],
            OLD_LOCATION: fields[OLD_LOCATION]["value"],
            NEW_LOCATION: fields[NEW_LOCATION]["value"],
        }
        for field, value in payload.items():
            if field != "action" and (field in REQUIRED_FIELDS or clean_text(value)):
                entry[field] = value
        entry.update(canonical_values)
        # 保留既有字段含义：旧表本次抄见读数写入“当前示数”，作为旧表最终止度来源。
        entry[PREVIOUS_READING] = fields[PREVIOUS_READING]["value"] or entry.get(PREVIOUS_READING, "")
        entry[CURRENT_READING] = fields[OLD_STOP_READING]["value"]
        if clean_text(payload.get("安装位置")):
            entry["安装位置"] = payload["安装位置"]
        elif fields[NEW_LOCATION]["value"]:
            entry["安装位置"] = fields[NEW_LOCATION]["value"]
        # 登记阶段仍围绕旧档案流转；新表号独立保留，不覆盖“表具编号”的档案含义。
        entry["表具状态"] = REPLACE_ACTION
        entry["换表信息"] = {field: entry.get(field, "") for field in REPLACEMENT_FIELDS}
        entry["换表提醒"] = rule["warnings"]

    def _with_rule(self, row: dict[str, Any]) -> dict[str, Any]:
        view = deepcopy(row)
        view["换表规则"] = evaluate_meter_replacement(
            view,
            explicit_fields=(),
            existing_meter_numbers=self._existing_meter_numbers(int(view.get("id", 0))),
        )
        return view
