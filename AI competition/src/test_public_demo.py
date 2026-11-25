"""Contract tests for fictional scores, links, portability and source separation."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from build_public_demo import build, build_cases, fictional_offerings, powerbi_tables


class PublicDemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = fictional_offerings()
        cls.cases = build_cases(cls.rows)
        cls.tables = powerbi_tables(cls.cases)

    def test_every_evidence_is_a_fictional_offering(self):
        source = {r["offering_id"]: r for r in self.rows}
        self.assertEqual(len(source), len(self.rows))
        for case in self.cases:
            self.assertTrue(case["course_code"].startswith("DEMO"))
            for candidate in case["candidates"]:
                self.assertRegex(candidate["name"], r"^示例教師 [A-F]$")
                seen = set()
                for evidence in candidate["evidence"]:
                    self.assertNotIn(evidence["id"], seen)
                    seen.add(evidence["id"])
                    original = source[evidence["id"]]
                    self.assertEqual(original["instructor_name"], candidate["name"])
                    self.assertEqual(original["term_code"], evidence["term"])
                    self.assertEqual(original["course_code"], evidence["course_code"])

    def test_formal_score_components_and_unsupported_candidates(self):
        main = next(c for c in self.cases if c["course_code"] == "DEMO101")
        teacher = next(c for c in main["candidates"] if c["id"] == "PUBLIC-TA")
        # Independent hand calculation: same-course last term index 18 / 20;
        # 3 same-course EMI and 2 other-course EMI; 3 same English + 2 others.
        self.assertEqual(teacher["scores"]["同課經驗"], 29.0)
        self.assertEqual(teacher["scores"]["正式 EMI"], 26.67)
        self.assertEqual(teacher["scores"]["英語授課"], 12.0)
        self.assertEqual(teacher["scores"]["新近性"], 9.5)
        low = next(c for c in self.cases if c["course_code"] == "DEMO401")
        self.assertEqual(len(low["candidates"]), 1)
        self.assertEqual(low["candidates"][0]["scores"]["正式 EMI"], 0)
        for case in self.cases:
            scores = [c["total_score"] for c in case["candidates"]]
            self.assertEqual(scores, sorted(scores, reverse=True))
            for candidate in case["candidates"]:
                self.assertEqual(len(candidate["scores"]), 5)
                self.assertTrue(0 <= candidate["total_score"] <= 100)
                self.assertAlmostEqual(sum(candidate["scores"].values()), candidate["total_score"], delta=0.021)

    def test_primary_foreign_keys_and_teacher_ownership(self):
        courses = {r["CourseCode"] for r in self.tables["Courses"]}
        candidates = {r["CandidateKey"]: r for r in self.tables["Candidates"]}
        self.assertEqual(len(candidates), len(self.tables["Candidates"]))
        self.assertTrue(all(c["CourseCode"] in courses for c in candidates.values()))
        for evidence in self.tables["Evidence"]:
            candidate = candidates[evidence["CandidateKey"]]
            self.assertEqual(candidate["Teacher"], evidence["Teacher"])

    def test_build_is_portable_deterministic_and_never_queries_database(self):
        with TemporaryDirectory() as temp, patch("recommend_teachers.frame", side_effect=AssertionError("DB access forbidden")):
            output = Path(temp)
            build(output)
            def hashes():
                return {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in output.rglob("*") if p.is_file()}
            first = hashes()
            build(output)
            self.assertEqual(first, hashes())
            model = json.loads((output / "EMI_Public.SemanticModel/model.bim").read_text(encoding="utf-8"))
            for table in model["model"]["tables"]:
                expression = "\n".join(table["partitions"][0]["source"]["expression"])
                self.assertIn("#table", expression)
                for prohibited in ("Sql.Database", "File.Contents", "Web.Contents", "outputs/", "C:\\", "E:\\"):
                    self.assertNotIn(prohibited, expression)
            bar = json.loads((output / "EMI_Public.Report/definition/pages/CandidateDetail/visuals/TeacherScores/visual.json").read_text(encoding="utf-8"))
            self.assertEqual(bar["visual"]["query"]["sortDefinition"]["sort"][0]["direction"], "Descending")
            page = json.loads((output / "EMI_Public.Report/definition/pages/CandidateDetail/page.json").read_text(encoding="utf-8"))
            self.assertTrue(any(r["source"] == "TeacherScores" and r["target"] == "Evidence" and r["type"] == "DataFilter"
                                for r in page["visualInteractions"]))


if __name__ == "__main__":
    unittest.main()
