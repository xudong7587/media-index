import unittest

from app.services.share_inspector import find_season_share_folders, inspect_share, parse_season_folder_number


class FakeQas:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def share_detail(self, share_url):
        self.calls.append(share_url)
        return self.responses[share_url]


class ShareInspectorTests(unittest.TestCase):
    def test_recognizes_common_season_folder_names(self):
        self.assertEqual(1, parse_season_folder_number("S01"))
        self.assertEqual(2, parse_season_folder_number("Season 2 1080P"))
        self.assertEqual(2, parse_season_folder_number("龙之家族 第二季"))
        self.assertEqual(12, parse_season_folder_number("第十二季"))
        self.assertIsNone(parse_season_folder_number("S01-S03 合集"))
        self.assertIsNone(parse_season_folder_number("1080P"))

    def test_discovers_sibling_seasons_below_media_wrapper(self):
        root = "https://pan.quark.cn/s/multi"
        wrapper = root + "#/list/share/show"
        qas = FakeQas(
            {
                root: {"data": {"list": [{"dir": True, "fid": "show", "file_name": "动画全集"}]}},
                wrapper: {
                    "data": {
                        "list": [
                            {"dir": True, "fid": "s1", "file_name": "S01"},
                            {"dir": True, "fid": "s2", "file_name": "第二季"},
                        ]
                    }
                },
            }
        )

        folders = find_season_share_folders(qas, root)

        self.assertEqual([1, 2], [folder.season_number for folder in folders])
        self.assertEqual(root + "#/list/share/s1", folders[0].share_url)
        self.assertEqual(root + "#/list/share/s2", folders[1].share_url)

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
