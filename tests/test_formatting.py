import unittest
import sys
import os

# Add parent directory to path to import jira_trans
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jira_trans import JiraTicketTranslator
from modules.formatting import format_bilingual_block, is_media_line, is_media_only_line

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

class TestMediaLineDetection(unittest.TestCase):
    """미디어 라인 감지 테스트"""

    def test_image_markup(self):
        self.assertTrue(is_media_line("!image.png!"))
        self.assertTrue(is_media_line("!P2-73589_B.jpg|thumbnail!"))

    def test_attachment_markup(self):
        self.assertTrue(is_media_line("[^video.mp4]"))
        self.assertTrue(is_media_line("[^P2-73589_A.mp4]"))

    def test_bullet_with_attachment(self):
        """불릿 뒤에 첨부파일이 있는 경우도 미디어 라인으로 인식"""
        self.assertTrue(is_media_line("- [^P2-73589_A.mp4]"))
        self.assertTrue(is_media_line("* !image.png!"))

    def test_media_with_text_is_media_line(self):
        """미디어+텍스트 혼합도 is_media_line은 True"""
        self.assertTrue(is_media_line("[^video.mp4] - description"))
        self.assertTrue(is_media_line("!image.png! - caption"))


class TestMediaOnlyLineDetection(unittest.TestCase):
    """순수 미디어 라인 감지 테스트 (is_media_only_line)"""

    def test_pure_media_lines(self):
        """미디어만 있는 라인은 True"""
        self.assertTrue(is_media_only_line("[^video.mp4]"))
        self.assertTrue(is_media_only_line("[^video.mp4],"))
        self.assertTrue(is_media_only_line("!image.png!"))
        self.assertTrue(is_media_only_line("!image.png|thumbnail!"))
        self.assertTrue(is_media_only_line("- [^video.mp4]"))

    def test_external_link_media(self):
        """외부 링크 형태의 미디어 파일도 미디어로 인식"""
        # [filename.mp4|url] 형태
        self.assertTrue(is_media_only_line("[P2-73589_A.mp4|https://example.com/video.mp4]"))
        self.assertTrue(is_media_only_line("[P2-73589_A.mp4|https://example.com/video.mp4],"))
        self.assertTrue(is_media_line("[P2-73589_A.mp4|https://example.com/video.mp4]"))

    def test_media_with_text_not_media_only(self):
        """미디어+텍스트 혼합 라인은 False"""
        self.assertFalse(is_media_only_line("[^video.mp4] - description"))
        self.assertFalse(is_media_only_line("!image.png! - caption text"))
        self.assertFalse(is_media_only_line("[^P2-73589_C.mp4] - showcases the issue"))

    def test_regular_text_not_media_only(self):
        """일반 텍스트는 False"""
        self.assertFalse(is_media_only_line("- This is regular text"))
        self.assertFalse(is_media_only_line("Some description"))


class TestMediaWithTextLine(unittest.TestCase):
    """
    미디어와 텍스트가 같은 줄에 있는 경우 처리 테스트.

    예: "[^video.mp4] - showcases the issue"
    현재 이런 라인은 is_media_line()이 True를 반환하여 번역되지 않음.
    """

    def test_media_with_inline_text_should_translate_text_part(self):
        """
        미디어와 텍스트가 같은 줄에 있을 때, 텍스트 부분은 번역되어야 함.

        예: "[^P2-73589_C.mp4] - showcases the issue"
        기대: 미디어는 보존하고 텍스트만 번역
        """
        original = "[^P2-73589_C.mp4] - showcases the issue occurring with Extraction Tunnels."
        translated = "[^P2-73589_C.mp4] - Extraction Tunnel에서 이슈가 발생하는 모습을 보여줍니다."

        result = format_bilingual_block(original, translated)

        # 미디어가 한 번만 나와야 함
        self.assertEqual(result.count("[^P2-73589_C.mp4]"), 1,
            f"Media should appear once.\nResult:\n{result}")

        # 번역된 텍스트가 포함되어야 함
        self.assertIn("Extraction Tunnel에서 이슈가 발생하는 모습을 보여줍니다", result,
            f"Translated text should be included.\nResult:\n{result}")


class TestBilingualBlockMediaDuplication(unittest.TestCase):
    """
    번역문에 미디어 마크업이 포함된 경우 중복 출력되는 버그 테스트.

    원인: LLM이 번역 시 미디어 마크업을 그대로 포함하여 반환하면,
    format_bilingual_block에서 원문의 미디어와 번역문의 미디어가 모두 출력됨.
    """

    def test_media_not_duplicated_when_translation_includes_media(self):
        """
        번역문에 미디어 마크업이 포함되어 있어도 중복 출력되지 않아야 함.

        시나리오:
        - 원문: "[^P2-73589_A.mp4],\n!P2-73589_B.jpg|thumbnail!\n- showcase the issue"
        - 번역문(LLM 응답): "[^P2-73589_A.mp4],\n!P2-73589_B.jpg|thumbnail!\n- 이슈를 보여줍니다"

        기대 결과: 미디어 마크업은 한 번만 출력되어야 함
        """
        original = "[^P2-73589_A.mp4],\n!P2-73589_B.jpg|thumbnail!\n- showcase the issue occurring during a Raid."

        # LLM이 미디어 마크업을 그대로 포함해서 반환하는 경우
        translated = "[^P2-73589_A.mp4],\n!P2-73589_B.jpg|thumbnail!\n- 레이드 중 이슈가 발생하는 모습을 보여줍니다."

        result = format_bilingual_block(original, translated, header="Video/영상:")

        # mp4 첨부파일이 한 번만 나와야 함
        mp4_count = result.count("[^P2-73589_A.mp4]")
        self.assertEqual(mp4_count, 1,
            f"mp4 attachment should appear exactly once, but found {mp4_count} times.\n"
            f"Result:\n{result}")

        # jpg 이미지도 한 번만 나와야 함
        jpg_count = result.count("P2-73589_B.jpg")
        self.assertEqual(jpg_count, 1,
            f"jpg image should appear exactly once, but found {jpg_count} times.\n"
            f"Result:\n{result}")

    def test_text_with_media_translated_correctly(self):
        """
        미디어와 텍스트가 섞인 경우, 텍스트만 번역되고 미디어는 보존되어야 함.
        """
        original = "[^video.mp4]\n- This is a test description.\n!screenshot.png!\n- Another line of text."

        # LLM이 미디어를 포함해서 반환
        translated = "[^video.mp4]\n- 테스트 설명입니다.\n!screenshot.png!\n- 또 다른 텍스트입니다."

        result = format_bilingual_block(original, translated)

        # 미디어가 중복되지 않아야 함
        self.assertEqual(result.count("[^video.mp4]"), 1,
            f"video.mp4 should appear once.\nResult:\n{result}")
        self.assertEqual(result.count("!screenshot.png!"), 1,
            f"screenshot.png should appear once.\nResult:\n{result}")

        # 번역된 텍스트는 포함되어야 함
        self.assertIn("테스트 설명입니다", result)
        self.assertIn("또 다른 텍스트입니다", result)


if __name__ == '__main__':
    unittest.main()
