import unittest
from powerbi_privacy import mask_teacher_name

class NameMaskTests(unittest.TestCase):
    def test_three_character_name(self):
        self.assertEqual(mask_teacher_name("王小明"), "王O明")

    def test_all_inner_characters(self):
        self.assertEqual(mask_teacher_name("歐陽小明"), "歐OO明")

    def test_short_and_empty(self):
        self.assertEqual(mask_teacher_name("王明"), "王O")
        self.assertEqual(mask_teacher_name("王"), "O")
        self.assertEqual(mask_teacher_name(None), "")

    def test_repeat_is_stable(self):
        for name in ["王小明", "歐陽小明", "王明", "", "王O明"]:
            self.assertEqual(mask_teacher_name(mask_teacher_name(name)), mask_teacher_name(name))

if __name__ == "__main__":
    unittest.main()
