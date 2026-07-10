import unittest

from app.services.share_inspector import inspect_share


class FakeQas:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def share_detail(self, share_url):
        self.calls.append(share_url)
        return self.responses[share_url]


class ShareInspectorTests(unittest.TestCase):
    def test_nested_qas_error_is_not_reported_as_empty_files(self):
        root = "https://pan.quark.cn/s/expired"
        qas = FakeQas({root: {"success": False, "data": {"error": "expired"}}})

        result = inspect_share(qas, root)

        self.assertFalse(result.valid)
        self.assertEqual("share_error:expired", result.error)

    def test_enters_shared_root_directory_before_reading_files(self):
        root = "https://pan.quark.cn/s/root"
        child = root + "#/list/share/folder-id"
        qas = FakeQas(
            {
                root: {
                    "data": {
                        "first_file": {"dir": True, "fid": "folder-id", "file_name": "Show"},
                        "first_fid": "folder-id",
                    }
                },
                child: {
                    "data": {
                        "files": [
                            {"dir": False, "file_name": "Show.S02E28.mkv", "size": 1000}
                        ]
                    }
                },
            }
        )

        result = inspect_share(qas, root)

        self.assertTrue(result.valid)
        self.assertEqual(child, result.share_url)
        self.assertEqual("Show.S02E28.mkv", result.files[0].name)
        self.assertEqual([root, child], qas.calls)


if __name__ == "__main__":
    unittest.main()
