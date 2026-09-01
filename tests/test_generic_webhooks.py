import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.config import get_settings
from app.db.database import db, init_db
from app.services import generic_webhooks


class FakeResponse:
    status = 204

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status


class GenericWebhookTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.environment = patch.dict(
            os.environ,
            {"DB_PATH": str(Path(self.tempdir.name) / "test.db")},
            clear=False,
        )
        self.environment.start()
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        self.environment.stop()
        get_settings.cache_clear()
        self.tempdir.cleanup()

    def test_inbound_accepts_standard_signature_and_deduplicates_event_id(self):
        connection = generic_webhooks.create_connection("自动化接收", "inbound", "", ["*"])
        body = json.dumps({
            "specversion": "1.0",
            "id": "evt-fixed",
            "source": "/test",
            "type": "example.completed",
            "data": {"ok": True},
        }, separators=(",", ":")).encode()
        timestamp = str(int(time.time()))
        headers = {
            "webhook-id": "evt-fixed",
            "webhook-timestamp": timestamp,
            "webhook-signature": generic_webhooks.sign_payload(
                connection["signing_secret"], "evt-fixed", timestamp, body
            ),
        }

        first, duplicate = generic_webhooks.accept_inbound(connection["endpoint_key"], body, headers)
        second, duplicate_again = generic_webhooks.accept_inbound(connection["endpoint_key"], body, headers)

        self.assertTrue(first["accepted"])
        self.assertFalse(duplicate)
        self.assertTrue(second["duplicate"])
        self.assertTrue(duplicate_again)
        self.assertEqual("verified", generic_webhooks.get_connection(connection["id"])["verification_state"])

    def test_inbound_rejects_stale_signature_but_supports_simple_bearer_mode(self):
        connection = generic_webhooks.create_connection("接收", "inbound", "", ["*"])
        body = b'{"hello":"world"}'
        stale = str(int(time.time()) - 3600)
        with self.assertRaisesRegex(PermissionError, "过期"):
            generic_webhooks.accept_inbound(connection["endpoint_key"], body, {
                "webhook-id": "evt-old",
                "webhook-timestamp": stale,
                "webhook-signature": generic_webhooks.sign_payload(
                    connection["signing_secret"], "evt-old", stale, body
                ),
            })

        result, duplicate = generic_webhooks.accept_inbound(connection["endpoint_key"], body, {
            "authorization": f"Bearer {connection['signing_secret']}",
        })
        self.assertTrue(result["accepted"])
        self.assertFalse(duplicate)

    @patch("app.services.generic_webhooks.open_url", return_value=FakeResponse())
    def test_outbound_uses_cloudevents_and_standard_webhook_headers(self, opened):
        connection = generic_webhooks.create_connection(
            "家庭自动化", "outbound", "https://hooks.example.test/media", ["failure"]
        )
        delivery_id = generic_webhooks.enqueue_test_event(connection["id"])

        request = opened.call_args.args[0]
        headers = {key.casefold(): value for key, value in request.header_items()}
        payload = json.loads(request.data)
        self.assertEqual("1.0", payload["specversion"])
        self.assertEqual("io.mediaindex.webhook.test", payload["type"])
        self.assertIn("webhook-id", headers)
        self.assertIn("webhook-timestamp", headers)
        self.assertTrue(headers["webhook-signature"].startswith("v1,"))
        self.assertEqual("delivered", generic_webhooks.list_deliveries(connection["id"])[0]["status"])
        self.assertEqual(delivery_id, generic_webhooks.list_deliveries(connection["id"])[0]["id"])

    def test_event_subscription_filters_notification_outbox(self):
        generic_webhooks.create_connection("只收失败", "outbound", "https://hooks.example.test/fail", ["failure"])
        generic_webhooks.create_connection("只收入库", "outbound", "https://hooks.example.test/library", ["library"])

        self.assertEqual(1, generic_webhooks.enqueue_outbound_event("failure", {"message": "boom"}))
        with db() as conn:
            rows = conn.execute("SELECT event_type,status FROM webhook_deliveries").fetchall()
        self.assertEqual([("failure", "queued")], [(row["event_type"], row["status"]) for row in rows])

    def test_public_http_is_rejected_while_lan_http_is_supported(self):
        with self.assertRaisesRegex(ValueError, "公网 Webhook 必须使用 HTTPS"):
            generic_webhooks.validate_target_url("http://hooks.example.com/events")
        self.assertEqual(
            "http://home-assistant:8123/api/webhook/mediaindex",
            generic_webhooks.validate_target_url("http://home-assistant:8123/api/webhook/mediaindex"),
        )
        with self.assertRaisesRegex(ValueError, "链路本地"):
            generic_webhooks.validate_target_url("http://169.254.169.254/latest/meta-data")

    def test_secret_is_only_returned_when_created_rotated_or_explicitly_revealed(self):
        connection = generic_webhooks.create_connection("发送端", "outbound", "https://hooks.example.test", ["*"])
        listed = generic_webhooks.list_connections()[0]
        self.assertNotIn("signing_secret", listed)
        self.assertTrue(connection["signing_secret"].startswith("whsec_"))
        rotated = generic_webhooks.rotate_secret(connection["id"])
        self.assertNotEqual(connection["signing_secret"], rotated["signing_secret"])
        self.assertEqual(rotated["signing_secret"], generic_webhooks.reveal_secret(connection["id"]))


if __name__ == "__main__":
    unittest.main()
