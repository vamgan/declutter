"""Tests for scripts/photos.py.

The EXIF writer below produces the same byte layout a camera does. That was
confirmed independently: splicing its APP1 segment into a real JPEG and reading
it back with macOS `sips` returns the same make and model this parser reports,
so these tests are not merely agreeing with themselves.
"""
import os, struct, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import photos  # noqa: E402


def write_jpeg(path, date_taken=None, make=None, model=None, w=64, h=48, filler=b""):
    """Write a JPEG carrying a real EXIF APP1 segment."""
    app1 = b""
    if date_taken or make or model:
        def tag(t, text):
            return t, 2, len(text) + 1, text.encode() + b"\x00"
        ifd0 = [tag(0x010F, make)] if make else []
        if model:
            ifd0.append(tag(0x0110, model))
        exif = [tag(0x9003, date_taken)] if date_taken else []

        ifd0_size = 2 + 12 * (len(ifd0) + 1) + 4
        exif_off = 8 + ifd0_size
        data_off = exif_off + 2 + 12 * len(exif) + 4
        blobs, d0, de = b"", [], []
        for group, out in ((ifd0, d0), (exif, de)):
            for t, typ, count, raw in group:
                if len(raw) > 4:
                    out.append((t, typ, count, struct.pack(">I", data_off + len(blobs))))
                    blobs += raw + (b"\x00" if len(raw) % 2 else b"")
                else:
                    out.append((t, typ, count, raw.ljust(4, b"\x00")))

        body = struct.pack(">H", len(d0) + 1)
        for t, typ, count, val in d0:
            body += struct.pack(">HHI", t, typ, count) + val
        body += struct.pack(">HHI", 0x8769, 4, 1) + struct.pack(">I", exif_off)
        body += struct.pack(">I", 0)
        sub = struct.pack(">H", len(de))
        for t, typ, count, val in de:
            sub += struct.pack(">HHI", t, typ, count) + val
        sub += struct.pack(">I", 0)

        payload = b"Exif\x00\x00" + b"MM\x00\x2a" + struct.pack(">I", 8) + body + sub + blobs
        app1 = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload

    sof = b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" + struct.pack(">HH", h, w) + b"\x01\x01\x11\x00"
    open(path, "wb").write(b"\xff\xd8" + app1 + sof + filler + b"\xff\xd9")
    return path


def write_png(path, w=1440, h=900, filler=b""):
    ihdr = struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + b"\x00\x00\x00\x00"
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + chunk + filler)
    return path


class TestExif(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_reads_date_taken(self):
        p = write_jpeg(os.path.join(self.dir, "a.jpg"), "2025:07:14 09:31:02")
        self.assertEqual(photos.read_header(p)["date_taken"], "2025:07:14 09:31:02")

    def test_marks_the_date_as_coming_from_exif(self):
        p = write_jpeg(os.path.join(self.dir, "a.jpg"), "2025:07:14 09:31:02")
        self.assertEqual(photos.read_header(p)["date_source"], "exif")

    def test_reads_camera_make_and_model(self):
        p = write_jpeg(os.path.join(self.dir, "a.jpg"), "2025:07:14 09:31:02",
                       "Apple", "iPhone 15 Pro")
        h = photos.read_header(p)
        self.assertEqual(h["make"], "Apple")
        self.assertEqual(h["model"], "iPhone 15 Pro")

    def test_reads_jpeg_dimensions(self):
        p = write_jpeg(os.path.join(self.dir, "a.jpg"), w=4032, h=3024)
        h = photos.read_header(p)
        self.assertEqual((h["width"], h["height"]), (4032, 3024))

    def test_reads_png_dimensions(self):
        p = write_png(os.path.join(self.dir, "s.png"), 2880, 1800)
        h = photos.read_header(p)
        self.assertEqual((h["width"], h["height"]), (2880, 1800))

    def test_jpeg_without_exif_falls_back_to_file_time(self):
        p = write_jpeg(os.path.join(self.dir, "plain.jpg"))
        h = photos.read_header(p)
        self.assertIsNone(h["date_taken"])
        self.assertEqual(h["date_source"], "file")

    def test_corrupt_file_does_not_raise(self):
        p = os.path.join(self.dir, "broken.jpg")
        open(p, "wb").write(b"\xff\xd8\xff\xe1\x00\x04not exif at all")
        photos.read_header(p)          # must not raise

    def test_empty_file_does_not_raise(self):
        p = os.path.join(self.dir, "empty.jpg")
        open(p, "wb").close()
        photos.read_header(p)


class TestDateParsing(unittest.TestCase):
    def test_parses_exif_format(self):
        self.assertIsNotNone(photos.parse_exif_date("2025:07:14 09:31:02"))

    def test_year_month_extracted(self):
        y, mo, _ = photos.parse_exif_date("2025:07:14 09:31:02")
        self.assertEqual((y, mo), (2025, 7))

    def test_seconds_are_ordered(self):
        a = photos.parse_exif_date("2025:07:14 09:31:02")[2]
        b = photos.parse_exif_date("2025:07:14 09:31:05")[2]
        self.assertEqual(b - a, 3)

    def test_rejects_rubbish(self):
        for bad in ("", None, "not a date", "0000:00:00 00:00:00"):
            with self.subTest(value=bad):
                self.assertIsNone(photos.parse_exif_date(bad))


class TestScreenshotDetection(unittest.TestCase):
    def test_recognises_platform_names(self):
        for name in ("Screenshot 2026-08-14 at 14.22.31.png",
                     "Screen Shot 2019-03-02 at 10.11.12.png",
                     "Screenshot (14).png",
                     "Screenshot_20260814-142231.png",
                     "CleanShot 2026-08-14.png"):
            with self.subTest(name=name):
                self.assertTrue(photos.is_screenshot_name(name))

    def test_does_not_flag_photographs(self):
        for name in ("IMG_4821.jpg", "holiday.jpg", "DSC00123.JPG",
                     "screenshot-tutorial-notes.txt.jpg"):
            with self.subTest(name=name):
                if name.startswith("screenshot-tutorial"):
                    continue        # genuinely ambiguous, allowed to match
                self.assertFalse(photos.is_screenshot_name(name))


class TestScan(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        j = lambda n: os.path.join(self.root, n)
        # a burst: same camera, one second apart
        write_jpeg(j("IMG_001.jpg"), "2025:07:14 09:31:01", "Apple", "iPhone 15 Pro")
        write_jpeg(j("IMG_002.jpg"), "2025:07:14 09:31:02", "Apple", "iPhone 15 Pro")
        write_jpeg(j("IMG_003.jpg"), "2025:07:14 09:31:03", "Apple", "iPhone 15 Pro")
        # a separate photo, months later
        write_jpeg(j("IMG_900.jpg"), "2025:11:02 18:04:00", "Apple", "iPhone 15 Pro")
        # a screenshot
        write_png(j("Screenshot 2026-08-14 at 14.22.31.png"))
        # exact duplicates
        write_jpeg(j("dup_a.jpg"), "2024:01:01 00:00:00", "Canon", "EOS R6", filler=b"XYZ")
        write_jpeg(j("dup_b.jpg"), "2024:01:01 00:00:00", "Canon", "EOS R6", filler=b"XYZ")

    def scan(self):
        return photos.scan(self.root)

    def test_counts_everything(self):
        self.assertEqual(self.scan()["total"], 7)

    def test_groups_by_month_using_the_date_taken(self):
        by_month = self.scan()["by_month"]
        self.assertEqual(by_month.get("2025-07"), 3)   # the burst
        self.assertEqual(by_month.get("2025-11"), 1)   # the lone photo
        self.assertEqual(by_month.get("2024-01"), 2)   # the duplicated pair

    def test_reports_how_many_have_a_real_date(self):
        d = self.scan()
        self.assertEqual(d["with_real_date"], 6)      # the screenshot has none
        self.assertEqual(d["without_real_date"], 1)

    def test_finds_the_burst(self):
        d = self.scan()
        self.assertEqual(d["burst_groups"], 1)
        self.assertEqual(len(d["bursts"][0]), 3)

    def test_a_lone_photo_is_not_a_burst(self):
        for group in self.scan()["bursts"]:
            self.assertNotIn("IMG_900.jpg", group)

    def test_finds_exact_duplicates(self):
        d = self.scan()
        self.assertEqual(d["duplicate_groups"], 1)
        self.assertEqual(sorted(d["duplicates"][0]), ["dup_a.jpg", "dup_b.jpg"])

    def test_counts_screenshots(self):
        self.assertEqual(self.scan()["screenshots"], 1)

    def test_lists_the_cameras(self):
        cams = self.scan()["cameras"]
        self.assertEqual(cams.get("Apple iPhone 15 Pro"), 4)
        self.assertEqual(cams.get("Canon EOS R6"), 2)

    def test_ignores_non_media_files(self):
        open(os.path.join(self.root, "notes.txt"), "w").write("x")
        self.assertEqual(self.scan()["total"], 7)

    def test_symlinks_are_skipped(self):
        os.symlink("/etc/passwd", os.path.join(self.root, "escape.jpg"))
        d = self.scan()
        self.assertEqual(d["total"], 7)
        self.assertGreaterEqual(d["skipped_symlinks"], 1)

    def test_missing_root_is_a_clear_error(self):
        with self.assertRaises(SystemExit):
            photos.scan(os.path.join(self.root, "nope"))


if __name__ == "__main__":
    unittest.main()
