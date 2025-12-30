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
        
        # NOTE: 현 구현은 텍스트를 "원문 블록 + (빈줄) + 번역 블록"으로 flush한 뒤
        # 미디어 라인을 출력한다. 즉, 첫 번째 아이템의 번역이 이미지 앞에 온다.
        expected = (
            "* Item 1\n"
            "\n"
            "* {color:#4c9aff}Item 1 Translated{color}\n"
            "!image.png!\n"
            "* Item 2\n\n"
            "* {color:#4c9aff}Item 2 Translated{color}"
        )
        
        result = self.translator._format_bilingual_block(original, translated)
        self.assertEqual(result, expected)

    def test_block_style_indentation(self):
        original = "  - Item 1\n    1. Item 2"
        translated = "- Item 1 Translated\n1. Item 2 Translated"
        
        expected = (
            # NOTE: _format_bilingual_block은 최종 결과에 strip()을 호출하므로,
            # 첫 줄의 leading whitespace는 제거된다.
            "- Item 1\n"
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
