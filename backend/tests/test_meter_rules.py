import unittest

from app.services.meter_record import MeterRecordService
from app.services.meter_rules import evaluate_meter_replacement
from app.store import store


class MeterReplacementRuleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = {
            "表具编号": "M-001",
            "安装位置": "一号 表位",
            "上次示数": "100.00",
            "当前示数": "110.50",
        }

    def test_boundary_readings_and_position_whitespace_are_valid(self) -> None:
        rule = evaluate_meter_replacement(
            self.base,
            {
                "新表表号": "M-002",
                "旧表止度": "110.50",
                "新表起度": "0",
                "旧表安装位置": "一号 表位",
                "新表安装位置": "一号表位",
            },
            has_replacement_input=True,
        )

        self.assertTrue(rule["allowed"])
        self.assertEqual(rule["issues"], [])

    def test_common_aliases_keep_field_meanings(self) -> None:
        rule = evaluate_meter_replacement(
            self.base,
            {"表号": "M-002", "止度": "1,234.50", "起度": "10"},
            explicit_fields=["表号", "止度", "起度"],
            has_replacement_input=True,
        )

        self.assertTrue(rule["allowed"], rule["issues"])
        self.assertEqual(rule["fields"]["旧表止度"]["value"], "1234.50")
        self.assertTrue(any("新表起度不是0" in warning for warning in rule["warnings"]))

    def test_null_and_invalid_historical_data_have_stable_results(self) -> None:
        empty = evaluate_meter_replacement({})
        history = evaluate_meter_replacement(
            {"表具编号": "M-001", "安装位置": "一号表位", "上次示数": "abc", "当前示数": None}
        )

        self.assertEqual(empty["status"], "待补录")
        self.assertFalse(empty["allowed"])
        self.assertEqual(history["status"], "历史异常")
        self.assertIn("上次示数不是有效读数", history["issues"])

    def test_explicit_empty_value_does_not_fallback_to_history(self) -> None:
        history = {**self.base, "旧表止度": "110.50"}
        rule = evaluate_meter_replacement(
            history,
            {"旧表止度": ""},
            explicit_fields=["旧表止度"],
            has_replacement_input=True,
        )

        self.assertFalse(rule["allowed"])
        self.assertIn("缺少旧表止度", rule["issues"])

    def test_negative_and_regressive_readings_are_rejected(self) -> None:
        rule = evaluate_meter_replacement(
            self.base,
            {"新表表号": "M-002", "旧表止度": "99", "新表起度": "-1"},
            has_replacement_input=True,
        )

        self.assertIn("旧表止度不能小于上次示数", rule["issues"])
        self.assertIn("旧表止度不能小于当前示数", rule["issues"])
        self.assertIn("新表起度不能小于0", rule["issues"])


class MeterRecordServiceRuleConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = MeterRecordService()
        self._original_rows = [dict(row) for row in store.rows("meter_record")]
        store.rows("meter_record").clear()

    def tearDown(self) -> None:
        store.rows("meter_record").clear()
        store.rows("meter_record").extend(self._original_rows)

    def test_list_detail_and_action_share_one_result(self) -> None:
        entry, missing = self.service.create_entry(
            {
                "表具编号": "M-LIST",
                "表具类型": "贸易结算表",
                "口径规格": "DN15",
                "安装位置": "一号 表位",
                "上次示数": "100",
                "当前示数": "110",
            }
        )
        self.assertEqual(missing, [])
        entry_id = int(entry["id"])

        listed = next(row for row in self.service.list_entries(size=100)[0] if row["id"] == entry_id)
        detail = self.service.get_entry(entry_id)
        self.assertEqual(listed["换表规则"], detail["换表规则"])

        rejected, message, rejected_rule = self.service.run_action(entry_id, "换表登记", {})
        self.assertIsNone(rejected)
        self.assertFalse(rejected_rule["allowed"])
        self.assertIn("缺少新表表号", message)

        accepted, _, accepted_rule = self.service.run_action(
            entry_id,
            "换表登记",
            {
                "表号": "M-NEW",
                "止度": "110",
                "起度": "0",
                "安装位置": "一号表位",
            },
        )
        self.assertIsNotNone(accepted)
        self.assertTrue(accepted_rule["allowed"])
        self.assertEqual(accepted["新表表号"], "M-NEW")
        self.assertEqual(accepted["旧表止度"], "110")
        self.assertEqual(accepted["当前示数"], "110")
        self.assertEqual(accepted["新表起度"], "0")


if __name__ == "__main__":
    unittest.main()
