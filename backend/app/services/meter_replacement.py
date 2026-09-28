"""贸易结算表换表规则。

列表、明细和换表处理入口都调用这里的同一组判断，避免同一字段在不同
入口被解释成不同口径。规则对象不直接读写仓库，便于对历史异常数据做
确定性的纯数据校验。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

# 当前在用表号与安装位置沿用台账原字段，换表过程字段单独命名，避免把
# “旧表止度/新表起度”与普通上次、当前示数混用。
OLD_METER_NO_FIELD = "旧表表号"
OLD_FINAL_READING_FIELD = "旧表止度"
NEW_METER_NO_FIELD = "新表表号"
NEW_INITIAL_READING_FIELD = "新表起度"
NEW_INSTALL_POSITION_FIELD = "新表安装位置"

CURRENT_METER_NO_FIELD = "表具编号"
CURRENT_INSTALL_POSITION_FIELD = "安装位置"

REPLACEMENT_FIELDS = (
    OLD_METER_NO_FIELD,
    OLD_FINAL_READING_FIELD,
    NEW_METER_NO_FIELD,
    NEW_INITIAL_READING_FIELD,
    NEW_INSTALL_POSITION_FIELD,
)

# 换表登记后仍保留待换表状态；真正完成的换表以登记过的新表字段为准。
REPLACEMENT_REGISTERED = "待换表"


@dataclass(frozen=True)
class ReplacementIssue:
    """单条字段级规则结果，code 供入口稳定判断，message 供页面展示。"""

    field: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "message": self.message}


@dataclass(frozen=True)
class ReplacementDecision:
    valid: bool
    issues: list[ReplacementIssue] = field(default_factory=list)
    readings: dict[str, float] = field(default_factory=dict)

    @property
    def message(self) -> str:
        return "换表信息校验通过" if self.valid else "；".join(issue.message for issue in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "message": self.message,
            "issues": [issue.as_dict() for issue in self.issues],
            "readings": dict(self.readings),
        }


def _text(value: Any) -> str:
    """把历史数据安全转成去首尾空白的文本；None 保持为空而不是 'None'。"""

    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value).strip()
    return ""


def _reading(value: Any) -> tuple[float | None, str | None]:
    """解析表计读数。

    None、空串视为未提供；0 是合法边界读数；负数、NaN、无穷大和无法
    解析的历史脏数据都得到无效，而不是在入口处抛异常。
    """

    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "missing"
    try:
        if isinstance(value, bool):
            raise ValueError
        number = float(value)
    except (TypeError, ValueError):
        return None, "invalid"
    if not math.isfinite(number) or number < 0:
        return None, "invalid"
    return number, None


def _missing_issue(field_name: str) -> ReplacementIssue:
    return ReplacementIssue(field_name, "missing", f"{field_name}不能为空")


def _invalid_issue(field_name: str) -> ReplacementIssue:
    return ReplacementIssue(field_name, "invalid", f"{field_name}必须是不小于0的有效读数")


def evaluate_replacement(
    values: Mapping[str, Any],
    *,
    current_meter_no: Any = None,
    current_install_position: Any = None,
    occupied_meter_nos: set[str] | None = None,
) -> ReplacementDecision:
    """按唯一规则源校验一次换表申请。

    values 可以是动作提交值，也可以是已登记记录；当前台账信息由参数
    显式传入，避免不同入口自行从不同字段取值。
    """

    issues: list[ReplacementIssue] = []
    readings: dict[str, float] = {}

    old_meter_no = _text(values.get(OLD_METER_NO_FIELD))
    old_final_reading_raw = values.get(OLD_FINAL_READING_FIELD)
    new_meter_no = _text(values.get(NEW_METER_NO_FIELD))
    new_initial_reading_raw = values.get(NEW_INITIAL_READING_FIELD)
    new_install_position = _text(values.get(NEW_INSTALL_POSITION_FIELD))

    current_no = _text(current_meter_no)
    current_position = _text(current_install_position)

    if not old_meter_no:
        issues.append(_missing_issue(OLD_METER_NO_FIELD))
    elif current_no and old_meter_no != current_no:
        issues.append(
            ReplacementIssue(
                OLD_METER_NO_FIELD,
                "mismatch",
                f"{OLD_METER_NO_FIELD}必须与当前表具编号一致",
            )
        )

    old_reading, old_reading_state = _reading(old_final_reading_raw)
    if old_reading_state == "missing":
        issues.append(_missing_issue(OLD_FINAL_READING_FIELD))
    elif old_reading_state == "invalid" or old_reading is None:
        issues.append(_invalid_issue(OLD_FINAL_READING_FIELD))
    else:
        readings[OLD_FINAL_READING_FIELD] = old_reading

    if not new_meter_no:
        issues.append(_missing_issue(NEW_METER_NO_FIELD))
    elif (old_meter_no and new_meter_no == old_meter_no) or (current_no and new_meter_no == current_no):
        issues.append(
            ReplacementIssue(
                NEW_METER_NO_FIELD,
                "duplicate",
                f"{NEW_METER_NO_FIELD}不能与旧表表号相同",
            )
        )
    elif new_meter_no in (occupied_meter_nos or set()):
        issues.append(
            ReplacementIssue(
                NEW_METER_NO_FIELD,
                "duplicate",
                f"{NEW_METER_NO_FIELD}已被其他贸易结算表占用",
            )
        )

    new_reading, new_reading_state = _reading(new_initial_reading_raw)
    if new_reading_state == "missing":
        issues.append(_missing_issue(NEW_INITIAL_READING_FIELD))
    elif new_reading_state == "invalid" or new_reading is None:
        issues.append(_invalid_issue(NEW_INITIAL_READING_FIELD))
    else:
        readings[NEW_INITIAL_READING_FIELD] = new_reading

    if not new_install_position:
        issues.append(_missing_issue(NEW_INSTALL_POSITION_FIELD))
    elif current_position and new_install_position != current_position:
        issues.append(
            ReplacementIssue(
                NEW_INSTALL_POSITION_FIELD,
                "mismatch",
                f"{NEW_INSTALL_POSITION_FIELD}必须与原安装位置一致",
            )
        )

    return ReplacementDecision(valid=not issues, issues=issues, readings=readings)
