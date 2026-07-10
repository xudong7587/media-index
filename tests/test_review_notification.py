import unittest

from app.services.review_notification import notify_review_required


class FakeQas:
    def task_data(self):
        return {"push_config": {"BARK_PUSH": "https://example.invalid/key", "BARK_GROUP": "MediaIndex"}}


class ReviewNotificationTests(unittest.TestCase):
    def test_qas_custom_webhook_template_is_supported(self):
        class WebhookQas:
            def task_data(self):
                return {
                    "push_config": {
                        "WEBHOOK_URL": "https://example.invalid/notify",
                        "WEBHOOK_METHOD": "POST",
                        "WEBHOOK_CONTENT_TYPE": "application/json",
                        "WEBHOOK_BODY": '{"title":"$title","content":"$content"}',
                    }
                }

        requests = []
        result = notify_review_required(
            "Test Show",
            "需要确认",
            7,
            qas=WebhookQas(),
            requester=lambda *args: requests.append(args),
        )

        self.assertTrue(result.sent)
        self.assertEqual(("webhook",), result.providers)
        self.assertIn("MediaIndex 需要确认", requests[0][1]["title"])

    def test_reuses_qas_push_configuration_without_exposing_values(self):
        requests = []

        def requester(url, data, headers, method):
            requests.append((url, data, headers, method))

        result = notify_review_required("Test Show", "需要确认", 42, qas=FakeQas(), requester=requester)

        self.assertTrue(result.sent)
        self.assertEqual(("bark",), result.providers)
        self.assertEqual("MediaIndex", requests[0][1]["group"])
        self.assertIn("任务 #42", requests[0][1]["body"])


if __name__ == "__main__":
    unittest.main()
