import unittest

from apps.qp.services.QP_downloader import (
    PaperRecord,
    build_direct_download_url,
    extract_drive_file_id,
    filter_papers,
    parse_paper_record,
    parse_selection_input,
)


class PaperParsingTests(unittest.TestCase):
    def test_parse_shifted_paper(self):
        record = parse_paper_record(
            {
                "paper": "JEE Main 2025 (22 Jan Shift 1) Previous Year Paper",
                "link": "https://drive.google.com/file/d/example/view",
            }
        )

        self.assertEqual(record.year, 2025)
        self.assertEqual(record.day, 22)
        self.assertEqual(record.month, "Jan")
        self.assertEqual(record.shift, "1")
        self.assertEqual(record.session_label, "22 Jan | Shift 1")

    def test_parse_online_paper(self):
        record = parse_paper_record(
            {
                "paper": "JEE Main 2018 (15 Apr Shift 1 Online) Previous Year Paper",
                "link": "https://drive.google.com/file/d/example/view",
            }
        )

        self.assertEqual(record.year, 2018)
        self.assertEqual(record.month, "Apr")
        self.assertEqual(record.mode, "Online")
        self.assertEqual(record.session_label, "15 Apr | Shift 1 | Online")

    def test_parse_year_only_paper(self):
        record = parse_paper_record(
            {
                "paper": "JEE Main 2011 Previous Year Paper",
                "link": "https://drive.google.com/file/d/example/view",
            }
        )

        self.assertEqual(record.year, 2011)
        self.assertIsNone(record.month)
        self.assertEqual(record.session_label, "General")


class SelectionTests(unittest.TestCase):
    def test_parse_selection_input_supports_ranges(self):
        self.assertEqual(parse_selection_input("1,3-5,2", 6), [1, 2, 3, 4, 5])

    def test_parse_selection_input_rejects_out_of_bounds(self):
        with self.assertRaises(ValueError):
            parse_selection_input("9", 3)


class DriveLinkTests(unittest.TestCase):
    def test_extract_drive_file_id(self):
        link = "https://drive.google.com/file/d/abc123_DEF/view"
        self.assertEqual(extract_drive_file_id(link), "abc123_DEF")

    def test_build_direct_download_url(self):
        link = "https://drive.google.com/file/d/abc123_DEF/view"
        self.assertEqual(
            build_direct_download_url(link),
            "https://drive.google.com/uc?export=download&id=abc123_DEF",
        )


class FilterTests(unittest.TestCase):
    def test_filter_papers_by_year_and_month(self):
        papers = [
            PaperRecord("A", "link-a", 2025, "Jan", 22, "1"),
            PaperRecord("B", "link-b", 2025, "Apr", 9, "2"),
            PaperRecord("C", "link-c", 2024, "Jan", 27, "1"),
        ]

        filtered = filter_papers(papers, years={2025}, months={"Jan"})

        self.assertEqual([paper.paper for paper in filtered], ["A"])
