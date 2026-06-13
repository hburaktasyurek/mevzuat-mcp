import unittest

import agent_search_helpers as helpers


class EmptySearchResult:
    documents = []
    total_results = 0
    error_message = None


class AgentSearchHelperTests(unittest.TestCase):
    def test_looks_like_full_text_query_detects_supported_syntax(self):
        self.assertTrue(helpers.looks_like_full_text_query("yolcu OR iptal"))
        self.assertTrue(helpers.looks_like_full_text_query('"yolcu haklari"'))
        self.assertTrue(helpers.looks_like_full_text_query("+yolcu -kurum"))
        self.assertTrue(helpers.looks_like_full_text_query("yolcu~"))
        self.assertFalse(helpers.looks_like_full_text_query("sivil havacilik"))

    def test_looks_like_short_code_query_detects_regulation_codes(self):
        self.assertTrue(helpers.looks_like_short_code_query("SHY-YOLCU"))
        self.assertTrue(helpers.looks_like_short_code_query("SHY"))
        self.assertFalse(helpers.looks_like_short_code_query("sivil havacilik yolcu haklari"))

    def test_plain_aranacak_ifade_routes_to_title(self):
        phrase, title, notes = helpers.resolve_bedesten_query_fields(
            aranacak_ifade="sivil havacilik"
        )

        self.assertEqual(phrase, "")
        self.assertEqual(title, "sivil havacilik")
        self.assertIn("Interpreted aranacak_ifade as mevzuat_adi.", notes)

    def test_boolean_aranacak_ifade_routes_to_phrase(self):
        phrase, title, notes = helpers.resolve_bedesten_query_fields(
            aranacak_ifade="yolcu haklari OR ucus iptali"
        )

        self.assertEqual(phrase, "yolcu haklari OR ucus iptali")
        self.assertEqual(title, "")
        self.assertIn("Interpreted aranacak_ifade as phrase.", notes)

    def test_full_text_title_query_moves_to_phrase(self):
        phrase, title, notes = helpers.resolve_bedesten_query_fields(
            mevzuat_adi="yolcu haklari OR ucus iptali"
        )

        self.assertEqual(phrase, "yolcu haklari OR ucus iptali")
        self.assertEqual(title, "")
        self.assertIn("Moved full-text style title query to phrase.", notes)

    def test_aranacak_ifade_is_not_silently_discarded_when_primary_field_exists(self):
        phrase, title, notes = helpers.resolve_bedesten_query_fields(
            phrase="iptal",
            aranacak_ifade="SHY-YOLCU",
        )

        self.assertEqual(phrase, "iptal")
        self.assertEqual(title, "")
        self.assertIn("Ignored aranacak_ifade because phrase, mevzuat_adi, or mevzuat_no was provided.", notes)

    def test_regulation_type_defaults_are_regulation_only(self):
        self.assertEqual(
            helpers.BED_REGULATION_TYPE_ORDER,
            ["KKY", "CB_YONETMELIK", "YONETMELIK", "UY"],
        )
        self.assertNotIn("TEBLIGLER", helpers.BED_REGULATION_TYPES)
        self.assertNotIn("KANUN", helpers.BED_REGULATION_TYPES)

    def test_validate_regulation_types_accepts_valid_input(self):
        tur_list, error = helpers.validate_regulation_types("KKY,UY")

        self.assertEqual(tur_list, ["KKY", "UY"])
        self.assertIsNone(error)

    def test_validate_regulation_types_rejects_non_regulation_type(self):
        tur_list, error = helpers.validate_regulation_types("KANUN")

        self.assertIsNone(tur_list)
        self.assertIn("Invalid mevzuat_tur", error)
        self.assertIn("KKY, CB_YONETMELIK, YONETMELIK, UY", error)

    def test_simplify_regulation_query_does_not_return_empty(self):
        self.assertEqual(helpers.simplify_regulation_query("yolcu haklari yonetmeligi"), "yolcu haklari")
        self.assertEqual(helpers.simplify_regulation_query("yonetmelik hakkinda"), "")

    def test_short_code_no_results_guidance_can_be_rendered(self):
        result = helpers.format_bedesten_search_result(
            EmptySearchResult(),
            search_desc="title='SHY-YOLCU'",
            mevzuat_tur="KKY,CB_YONETMELIK,YONETMELIK,UY",
            page=1,
            tried=["title: title='SHY-YOLCU'"],
            no_results_guidance=(
                "Short/common regulation codes may not appear in official titles. "
                "Do not repeat the same short-code title search blindly."
            ),
        )

        self.assertIn("No results found", result)
        self.assertIn("Tried strategies:", result)
        self.assertIn("Short/common regulation codes may not appear in official titles", result)


if __name__ == "__main__":
    unittest.main()
