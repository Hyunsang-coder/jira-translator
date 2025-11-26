import unittest
import sys
import os

# Add parent directory to path to import jira_trans
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jira_trans import JiraTicketTranslator

class TestFormatting(unittest.TestCase):
    def setUp(self):
        self.translator = JiraTicketTranslator(
            jira_url="https://example.com",
            email="test@example.com",
            api_token="token",
            openai_api_key="key"
        )

    def test_standard_bullet(self):
        original = "* Item"
        translated = "* Item Translated"
        expected = "* {color:#4c9aff}Item Translated{color}"
        result = self.translator._match_translated_line_format(original, translated)
        self.assertEqual(result, expected)

    def test_indented_bullet(self):
        original = "  - Item"
        translated = "- Item Translated" # Translator might strip indent or return standard bullet
        expected = "  - {color:#4c9aff}Item Translated{color}"
        result = self.translator._match_translated_line_format(original, translated)
        self.assertEqual(result, expected)

    def test_numbered_list(self):
        original = "1. Item"
        translated = "1. Item Translated"
        expected = "1. {color:#4c9aff}Item Translated{color}"
        result = self.translator._match_translated_line_format(original, translated)
        self.assertEqual(result, expected)

    def test_indented_numbered_list(self):
        original = "    1. Item"
        translated = "1. Item Translated"
        expected = "    1. {color:#4c9aff}Item Translated{color}"
        result = self.translator._match_translated_line_format(original, translated)
        self.assertEqual(result, expected)

    def test_plain_text(self):
        original = "Text"
        translated = "Text Translated"
        expected = "{color:#4c9aff}Text Translated{color}"
        result = self.translator._match_translated_line_format(original, translated)
        self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()
