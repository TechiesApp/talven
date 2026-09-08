import unittest

from experiments.metrics import aggregate, summarize_trial, validate_usage


class MetricsTests(unittest.TestCase):
    def usage(self, **changes):
        # Synthetic values exercise accounting only; never benchmark evidence.
        result = dict(input_tokens=100, output_tokens=20, cached_input_tokens=40,
                      usage_source="synthetic test receipt", model_cost_usd="0.10",
                      model_cost_source="synthetic test billing", tool_cost_usd="0",
                      tool_cost_source="test adapter used no tools")
        result.update(changes)
        return result

    def test_repair_usage_and_cost_include_failed_attempt(self):
        attempts = [{"usage": self.usage()}, {"usage": self.usage(input_tokens=200)}]
        result = summarize_trial(attempts, "live", {"amount_usd": "0.05", "source": "test receipt"})
        self.assertEqual(300, result["input_tokens"])
        self.assertEqual(40, result["output_tokens"])
        self.assertEqual(80, result["cached_input_tokens"])
        self.assertEqual(1, result["repair_attempts"])
        self.assertEqual("0.25", result["total_task_cost_usd"])

    def test_unknown_measurements_do_not_become_zero_or_partial_totals(self):
        result = summarize_trial([{"usage": self.usage()}, {"usage": None}], "live")
        self.assertIsNone(result["input_tokens"])
        self.assertIsNone(result["model_cost_usd"])
        self.assertIsNone(result["total_task_cost_usd"])
        known = summarize_trial([{"usage": self.usage()}], "live")
        self.assertEqual("0.1", known["model_cost_usd"])
        self.assertIsNone(known["total_task_cost_usd"])

    def test_fixture_usage_is_never_reported_as_model_measurement(self):
        result = summarize_trial([{"usage": self.usage()}], "fixture")
        self.assertIsNone(result["input_tokens"])
        self.assertIsNone(result["model_cost_usd"])

    def test_invalid_metrics_and_missing_provenance_are_rejected(self):
        for changes in ({"input_tokens": True}, {"output_tokens": -1},
                        {"input_tokens": 1.5}, {"cached_input_tokens": 101},
                        {"usage_source": None}, {"model_cost_usd": "NaN"},
                        {"model_cost_usd": "-1"}, {"model_cost_source": ""},
                        {"model_cost_usd": 0.1}, {"model_cost_usd": "0e99999999"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_usage(self.usage(**changes))

    def test_total_cost_per_correct_includes_unsuccessful_tasks(self):
        metrics = summarize_trial([{"usage": self.usage()}], "live",
                                  {"amount_usd": "0.05", "source": "test receipt"})
        result = aggregate([{"status": "passed", "metrics": metrics},
                            {"status": "failed", "metrics": metrics}])
        self.assertEqual(0.5, result["correctness_rate"])
        self.assertEqual("0.3", result["cost_per_correct_task_usd"])
        self.assertIsNone(aggregate([{"status": "failed", "metrics": metrics}])[
            "cost_per_correct_task_usd"])

    def test_empty_run_has_no_correctness_or_cost_claim(self):
        result = aggregate([])
        self.assertIsNone(result["correctness_rate"])
        self.assertIsNone(result["total_task_cost_usd"])
