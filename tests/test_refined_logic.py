import unittest
import sys
import os

# Add parent directory to path to import jira_trans
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jira_trans import JiraTicketTranslator

class TestRefinedLogic(unittest.TestCase):
    def setUp(self):
        self.translator = JiraTicketTranslator(
            jira_url="https://example.com",
            email="test@example.com",
            api_token="token",
            openai_api_key="key"
        )

    def test_skip_logic_with_content(self):
        # Should return True because it has content inside color tags
        text = "{color:#4c9aff}Translated Content{color}"
        self.assertTrue(self.translator._is_description_already_translated(text))

    def test_skip_logic_empty_tag(self):
        # Should return False because tag is empty or just structure
        text = "{color:#4c9aff}|{color}"
        self.assertFalse(self.translator._is_description_already_translated(text))

    def test_table_translation(self):
        original = "| Cell 1 | Cell 2 |"
        translated = "Cell 1 Translated\nCell 2 Translated"
        
        # Table translation is now skipped, so expect original string
        expected = original
        
        result = self.translator._format_bilingual_block(original, translated)
        self.assertEqual(result, expected)

    def test_media_placement(self):
        original = "Text Line 1\n!image.png!\nText Line 2"
        translated = "Text Line 1 Translated\n!image.png!\nText Line 2 Translated"
        
        expected = (
            "Text Line 1\n"
            "{color:#4c9aff}Text Line 1 Translated{color}\n"
            "!image.png!\n"
            "Text Line 2\n"
            "{color:#4c9aff}Text Line 2 Translated{color}"
        )
        
        result = self.translator._format_bilingual_block(original, translated)
        self.assertEqual(result, expected)

    def test_media_placement_multiple_lines(self):
        original = "Text 1\nText 2\n!image.png!"
        translated = "Text 1 Trans\nText 2 Trans\n!image.png!"
        
        expected = (
            "Text 1\n"
            "Text 2\n"
            "{color:#4c9aff}Text 1 Trans{color}\n"
            "{color:#4c9aff}Text 2 Trans{color}\n"
            "!image.png!"
        )
        
        result = self.translator._format_bilingual_block(original, translated)
        self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()
