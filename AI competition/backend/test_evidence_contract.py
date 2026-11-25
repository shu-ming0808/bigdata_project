from pathlib import Path
from unittest import IsolatedAsyncioTestCase

import httpx

from backend.app import Draft, Evidence, ExplanationInput, JsonCourseRepository, LocalProvider, create_app, explain_facts


class EvidenceContractTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.repo = JsonCourseRepository(Path(__file__).with_name("case.json"))

    async def test_missing_actual_data_requires_explicit_source_switch(self):
        app = create_app(self.repo, LocalProvider())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            url = "/api/courses/CE2005"
            self.assertEqual((await client.get(url + "/candidates")).status_code, 503)
            selection = {"candidate_ids": ["A", "B"]}
            self.assertEqual((await client.post(url + "/explanation", json=selection)).status_code, 503)
            case = (await client.get(url + "/candidates?synthetic=true")).json()
            self.assertEqual(case["data_source"], "synthetic")
            first, second = case["candidates"]
            self.assertEqual(first["facts"]["unknown_emi"], ["E1"])
            self.assertEqual(first["facts"]["formal"], [])
            self.assertEqual(second["facts"]["formal"], ["E2"])
            self.assertEqual(second["facts"]["same_formal"], [])

    def test_model_cannot_claim_formal_emi_for_unknown_record(self):
        case = self.repo.get_case("CE2005")
        payload = ExplanationInput(**case.model_dump(), comparison=None)
        draft = Draft.model_validate({"reasons": [{"candidate_id": "A", "fact": "formal"}]})
        with self.assertRaises(ValueError):
            explain_facts(payload, draft, "codex")

    def test_legacy_display_labels_have_course_codes(self):
        for label, expected in [("CE2005", "CE2005"), ("CE2005 示例", "CE2005"), ("相關課程 DEMO101", "DEMO101")]:
            evidence = Evidence(id="E", course=label, term="1", language="英語", emi="未知")
            self.assertEqual(evidence.course_code, expected)
