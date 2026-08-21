import io
import unittest

from app.services.bounded_range_stream import BoundedRangeStream, RangeStreamError, iter_range_chunks


class BoundedRangeStreamTests(unittest.TestCase):
    def test_reads_and_seeks_without_exceeding_memory_bound(self):
        source = b"abcdefghijkl"
        calls = []

        def read_range(start, end, limit):
            calls.append((start, end, limit))
            self.assertLessEqual(end - start + 1, limit)
            return source[start : end + 1]

        stream = BoundedRangeStream(len(source), read_range, buffer_bytes=4)
        self.assertEqual(b"abcd", stream.read())
        self.assertEqual(4, stream.tell())
        self.assertEqual(6, stream.seek(2, io.SEEK_CUR))
        self.assertEqual(b"ghij", stream.read(10))
        self.assertEqual([(0, 3, 4), (6, 9, 4)], calls)

    def test_rejects_incomplete_remote_range_without_writing_a_file(self):
        stream = BoundedRangeStream(8, lambda _start, _end, _limit: b"short", buffer_bytes=4)
        with self.assertRaisesRegex(RangeStreamError, "长度"):
            stream.read(4)

    def test_hash_or_upload_worker_can_iterate_fixed_size_chunks(self):
        source = b"abcdefghij"
        chunks = list(iter_range_chunks(len(source), lambda start, end, _limit: source[start : end + 1], chunk_bytes=3))
        self.assertEqual([b"abc", b"def", b"ghi", b"j"], chunks)

    def test_progress_callback_reports_current_remote_position(self):
        progress = []
        stream = BoundedRangeStream(
            6,
            lambda start, end, _limit: b"abcdef"[start : end + 1],
            buffer_bytes=4,
            on_read=progress.append,
        )
        self.assertEqual(b"abcd", stream.read())
        self.assertEqual(b"ef", stream.read())
        self.assertEqual([4, 6], progress)


if __name__ == "__main__":
    unittest.main()
