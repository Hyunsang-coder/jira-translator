import unittest
import sys
import os

# Add parent directory to path to import jira_trans
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jira_trans import JiraTicketTranslator

class TestBlockFormatting(unittest.TestCase):
    def setUp(self):
        self.translator = JiraTicketTranslator(
            jira_url="https://example.com",
            email="test@example.com",
            api_token="token",
            openai_api_key="key"
        )

    def test_block_style_basic(self):
        original = "* Item 1\n* Item 2"
        translated = "* Item 1 Translated\n* Item 2 Translated"
        
        expected = (
            "* Item 1\n"
            "* Item 2\n\n"
            "* {color:#4c9aff}Item 1 Translated{color}\n"
            "* {color:#4c9aff}Item 2 Translated{color}"
        )
        
        result = self.translator._format_bilingual_block(original, translated)
        self.assertEqual(result, expected)

    def test_block_style_with_media(self):
        original = "* Item 1\n!image.png!\n* Item 2"
        translated = "* Item 1 Translated\n!image.png!\n* Item 2 Translated"
        
        # Media should be in original block, but skipped in translation block
        expected = (
            "* Item 1\n"
            "!image.png!\n"
            "* Item 2\n\n"
            "* {color:#4c9aff}Item 1 Translated{color}\n"
            "* {color:#4c9aff}Item 2 Translated{color}"
        )
        
        result = self.translator._format_bilingual_block(original, translated)
        self.assertEqual(result, expected)

    def test_block_style_indentation(self):
        original = "  - Item 1\n    1. Item 2"
        translated = "- Item 1 Translated\n1. Item 2 Translated"
        
        expected = (
            "  - Item 1\n"
            "    1. Item 2\n\n"
            "  - {color:#4c9aff}Item 1 Translated{color}\n"
            "    1. {color:#4c9aff}Item 2 Translated{color}"
        )
        
        result = self.translator._format_bilingual_block(original, translated)
        self.assertEqual(result, expected)

    def test_block_style_with_header(self):
        header = "Expected Result"
        original = "* Item 1"
        translated = "* Item 1 Translated"
        
        expected = (
            "Expected Result\n"
            "* Item 1\n\n"
            "* {color:#4c9aff}Item 1 Translated{color}"
        )
        
        result = self.translator._format_bilingual_block(original, translated, header=header)
        self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()
