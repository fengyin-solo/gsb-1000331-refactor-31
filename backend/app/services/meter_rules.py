"""贸易结算水表换表规则的唯一来源。

列表、详情和处理入口都只调用 :func:`evaluate_meter_replacement`，避免同一组
旧表止度、新表起度、表号、安装位置判断在不同入口出现不同口径。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Sequence

# 换表信息的规范字段名；接口仍兼容括号中的业务别名。
OLD_METER_NO = "旧表表号"
NEW_METER_NO = "新表表号"
OLD_STOP_READING = "旧表止度"
NEW_START_READING = "新表起度"
OLD_LOCATION = "旧表安装位置"
NEW_LOCATION = "新表安装位置"
PREVIOUS_READING = "上次示数"
CURRENT_READING = "当前示数"

REPLACEMENT_FIELDS = [
    OLD_METER_NO,
    NEW_METER_NO,
    OLD_STOP_READING,
    NEW_START_READING,
    OLD_LOCATION,
    NEW_LOCATION,
]
NUMERIC_FIELDS = (OLD_STOP_READING, NEW_START_READING, PREVIOUS_READING, CURRENT_READING)

# 别名只在“本次提交显式传入”时映射到新表字段，避免历史记录里的“表号”被误判。
EXPLICIT_ALIASES = {
    NEW_METER_NO: ("新表编号", "新表号", "新表表具编号", "表号"),
    NEW_START_READING: ("新表起始读数", "起度", "新表起始示数", "新表底数"),
    NEW_LOCATION: ("新表位置", "新装位置"),
}
FALLBACK_ALIASES = {
    OLD_METER_NO: ("旧表编号", "旧表号", "旧表表具编号", "原表号", "原表编号", "表具编号"),
    NEW_METER_NO: ("新表编号", "新表号", "新表表具编号"),
    OLD_STOP_READING: ("旧表结束读数", "止度", "旧表末次读数", "旧表末次示数"),
    NEW_START_READING: ("新表起始读数", "起度", "新表起始示数", "新表底数"),
    OLD_LOCATION: ("旧表位置", "原安装位置", "原位置", "安装位置"),
    NEW_LOCATION: ("新表位置", "新装位置", "安装位置"),
    PREVIOUS_READING: ("上次数", "上次读数", "上次抄表读数"),
    CURRENT_READING: ("当前读数", "本次示数", "当前抄表读数"),
}


def clean_text(value: Any) -> str:
    """把 None、数字等外部值按字段文本含义归一化；只去除首尾空白。"""
    if value is None:
        return ""
    return str(value).strip()


def _compact_location(value: str) -> str:
    """安装位置比较口径：去除全部空白，但保留文字、标点和大小写。"""
    return "".join(value.split())


def parse_reading(value: Any) -> tuple[Decimal | None, bool]:
    """解析水表读数。

    返回 ``(读数, 是否可解析)``。空值不是非法历史数据，返回 ``(None, True)``；
    带单位、科学计数法、负数等无法作为抄表止度/起度的值返回 False。
    """
    if value is None:
        return None, True
    if isinstance(value, bool):
        return None, False
    if isinstance(value, int):
        return Decimal(value), True
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None, False
        return Decimal(str(value)), True
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None, False
        return value, True

    text = clean_text(value)
    if not text:
        return None, True
    text = text.replace(",", "")
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None, False
    if not parsed.is_finite():
        return None, False
    return parsed, True


def _reading_value(raw: Any) -> dict[str, Any]:
    if raw is None or clean_text(raw) == "":
        return {"raw": "", "value": "", "valid": True, "missing": True}
    value, valid = parse_reading(raw)
    return {
        "raw": clean_text(raw),
        "value": format(value, "f") if value is not None else "",
        "valid": valid,
        "missing": False,
    }


def _first_value(data: dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = data.get(key)
        if clean_text(value):
            return value
    return None


def _field_value(
    field: str,
    data: dict[str, Any],
    explicit_fields: Iterable[str] | None,
    explicit_empty: set[str],
) -> Any:
    explicit = set(explicit_fields or ())
    explicit_keys = tuple(EXPLICIT_ALIASES.get(field, ()))
    for alias in explicit_keys:
        if alias in explicit:
            return "" if alias in explicit_empty else data.get(alias)
    if field in explicit:
        return "" if field in explicit_empty else data.get(field)
    aliases = FALLBACK_ALIASES.get(field, ())
    for alias in aliases:
        if alias in explicit:
            return "" if alias in explicit_empty else data.get(alias)
    keys = (field, *aliases)
    return _first_value(data, keys)


def _text_field(field: str, raw: Any) -> dict[str, str]:
    value = clean_text(raw)
    return {"raw": value, "value": value, "valid": bool(value), "missing": not bool(value)}


def evaluate_meter_replacement(
    row: dict[str, Any] | None = None,
    submitted: dict[str, Any] | None = None,
    *,
    explicit_fields: Iterable[str] | None = None,
    existing_meter_numbers: Iterable[str] | None = None,
    has_replacement_input: bool | None = None,
) -> dict[str, Any]:
    """按同一套规则评估一条贸易结算表的换表信息。

    ``row`` 是档案/历史数据，``submitted`` 是处理入口本次提交的数据。列表和
    详情只传 ``row`` 也会得到同样结构；处理入口把两处数据合并后再判断。
    """
    history = dict(row or {})
    payload = dict(submitted or {})
    explicit = {clean_text(field) for field in (explicit_fields or payload.keys())}
    explicit_empty = {key for key, value in payload.items() if not clean_text(value)}
    submitted_keys = {_canonical_field(key) for key in explicit if _canonical_field(key) in REPLACEMENT_FIELDS}
    has_input = bool(submitted_keys) if has_replacement_input is None else has_replacement_input

    data = dict(history)
    # 提交值优先级高于历史值；空字符串显式表示清空前，也不能回退到旧值。
    for key, value in payload.items():
        data[key] = value

    fields = {
        OLD_METER_NO: _text_field(OLD_METER_NO, _field_value(OLD_METER_NO, data, explicit, explicit_empty)),
        NEW_METER_NO: _text_field(NEW_METER_NO, _field_value(NEW_METER_NO, data, explicit, explicit_empty)),
        OLD_LOCATION: _text_field(OLD_LOCATION, _field_value(OLD_LOCATION, data, explicit, explicit_empty)),
        NEW_LOCATION: _text_field(NEW_LOCATION, _field_value(NEW_LOCATION, data, explicit, explicit_empty)),
        PREVIOUS_READING: _reading_value(_field_value(PREVIOUS_READING, data, explicit, explicit_empty)),
        CURRENT_READING: _reading_value(_field_value(CURRENT_READING, data, explicit, explicit_empty)),
        OLD_STOP_READING: _reading_value(_field_value(OLD_STOP_READING, data, explicit, explicit_empty)),
        NEW_START_READING: _reading_value(_field_value(NEW_START_READING, data, explicit, explicit_empty)),
    }

    issues: list[str] = []
    warnings: list[str] = []

    old_no = fields[OLD_METER_NO]
    new_no = fields[NEW_METER_NO]
    old_location = fields[OLD_LOCATION]
    new_location = fields[NEW_LOCATION]
    previous = fields[PREVIOUS_READING]
    current = fields[CURRENT_READING]
    old_stop = fields[OLD_STOP_READING]
    new_start = fields[NEW_START_READING]

    if old_no["missing"] and has_input:
        issues.append("缺少旧表表号")
    if new_no["missing"] and has_input:
        issues.append("缺少新表表号")
    elif old_no["valid"] and new_no["value"] == old_no["value"]:
        issues.append("新表表号不能与旧表表号相同")

    existing = {clean_text(number) for number in (existing_meter_numbers or ()) if clean_text(number)}
    if old_no["value"]:
        existing.discard(old_no["value"])
    if new_no["valid"] and new_no["value"] in existing:
        issues.append("新表表号已存在，不能重复建档")

    if old_location["missing"] and has_input:
        issues.append("缺少旧表安装位置")
    if new_location["missing"] and has_input:
        issues.append("缺少新表安装位置")
    elif old_location["valid"] and _compact_location(old_location["value"]) != _compact_location(new_location["value"]):
        issues.append("新表安装位置必须与旧表安装位置一致")

    for label, reading in (
        ("上次示数", previous),
        ("当前示数", current),
        ("旧表止度", old_stop),
        ("新表起度", new_start),
    ):
        if not reading["valid"]:
            issues.append(f"{label}不是有效读数")
            reading["issue"] = "invalid"

    if has_input:
        for label, reading in (("旧表止度", old_stop), ("新表起度", new_start)):
            if reading["missing"]:
                issues.append(f"缺少{label}")

    previous_value = Decimal(previous["value"]) if previous["valid"] and not previous["missing"] else None
    current_value = Decimal(current["value"]) if current["valid"] and not current["missing"] else None
    stop_value = Decimal(old_stop["value"]) if old_stop["valid"] and not old_stop["missing"] else None
    start_value = Decimal(new_start["value"]) if new_start["valid"] and not new_start["missing"] else None

    for label, value in (
        ("上次示数", previous_value),
        ("当前示数", current_value),
        ("旧表止度", stop_value),
        ("新表起度", start_value),
    ):
        if value is not None and value < Decimal("0"):
            issues.append(f"{label}不能小于0")
            fields[_label_to_field(label)]["issue"] = "negative"

    # 上次示数=当前示数是停走边界，不直接作为换表字段错误；由表具状态流程处理。
    if previous_value is not None and current_value is not None and current_value < previous_value:
        issues.append("当前示数不能小于上次示数")
        current["issue"] = "regressed"

    if previous_value is not None and stop_value is not None and stop_value < previous_value:
        issues.append("旧表止度不能小于上次示数")
        old_stop["issue"] = "regressed"
    if current_value is not None and stop_value is not None and stop_value < current_value:
        issues.append("旧表止度不能小于当前示数")
        old_stop["issue"] = "regressed"

    if start_value is not None and start_value != Decimal("0"):
        warnings.append("新表起度不是0，请确认是否为出厂底度")
    if start_value is not None and stop_value is not None and start_value > stop_value:
        warnings.append("新表起度高于旧表止度，请复核两块表的读数")

    missing_required = [
        OLD_METER_NO,
        NEW_METER_NO,
        OLD_STOP_READING,
        NEW_START_READING,
        OLD_LOCATION,
        NEW_LOCATION,
    ]
    incomplete = any(fields[field]["missing"] for field in missing_required)
    missing_fields = [field for field in missing_required if fields[field]["missing"]]

    if issues:
        status = "历史异常" if not has_input else "不可换表"
        allowed = False
    elif incomplete:
        status = "待补录"
        allowed = False
    else:
        status = "可换表"
        allowed = True

    if not has_input and not issues:
        # 列表/详情查看历史档案时，缺换表信息不应误报成数据异常。
        status = "待补录"

    return {
        "status": status,
        "allowed": allowed,
        "issues": issues,
        "missingFields": missing_fields,
        "warnings": warnings,
        "fields": fields,
        "hasReplacementInput": has_input,
    }


def _label_to_field(label: str) -> str:
    return {
        "上次示数": PREVIOUS_READING,
        "当前示数": CURRENT_READING,
        "旧表止度": OLD_STOP_READING,
        "新表起度": NEW_START_READING,
    }[label]


def _canonical_field(key: str) -> str:
    cleaned = clean_text(key)
    if cleaned in REPLACEMENT_FIELDS or cleaned in (PREVIOUS_READING, CURRENT_READING):
        return cleaned
    for canonical, aliases in {**EXPLICIT_ALIASES, **FALLBACK_ALIASES}.items():
        if cleaned in aliases:
            return canonical
    return cleaned
