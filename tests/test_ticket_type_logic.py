import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path to import jira_trans
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jira_trans import JiraTicketTranslator
from modules.jira_client import JiraClient, STEPS_FIELD_CANDIDATES

class TestTicketTypeLogic(unittest.TestCase):
    def setUp(self):
        self.translator = JiraTicketTranslator(
            jira_url="https://example.com",
            email="test@example.com",
            api_token="token",
            openai_api_key="key"
        )
        # Mock external dependencies
        self.translator.jira_client.detect_steps_field = MagicMock(return_value=None)
        self.translator.fetch_issue_fields = MagicMock(return_value={})
        self.translator._call_openai_batch = MagicMock(return_value={})
        self.translator.update_issue_fields = MagicMock()
        self.translator._load_glossary_terms = MagicMock(return_value={"term": "translation"})
        
        # Patch the TranslationEngine._load_glossary_terms inside the Facade's component
        # Because in the new architecture, the Facade delegates this to the Engine
        self.translator.translation_engine._load_glossary_terms = self.translator._load_glossary_terms

    def test_pubg_ticket_logic(self):
        """Test that PUBG tickets use customfield_10237 and pubg_glossary.json"""
        issue_key = "PUBG-123"
        
        self.translator.translate_issue(issue_key)
        
        # Verify glossary loading
        self.translator._load_glossary_terms.assert_called_with("pubg_glossary.json")
        self.assertEqual(self.translator.glossary_name, "PUBG")
        
        # Verify fields fetched (should include customfield_10237)
        call_args = self.translator.fetch_issue_fields.call_args
        self.assertIsNotNone(call_args)
        fields_arg = call_args[0][1] # second argument
        self.assertIn("customfield_10237", fields_arg)
        self.assertNotIn("customfield_10399", fields_arg)

    def test_pbb_ticket_logic(self):
        """Test that PBB tickets use customfield_10399 and pbb_glossary.json"""
        issue_key = "P2-123"
        
        self.translator.translate_issue(issue_key)
        
        # Verify glossary loading
        self.translator._load_glossary_terms.assert_called_with("pbb_glossary.json")
        self.assertEqual(self.translator.glossary_name, "PBB(Project Black Budget)")
        
        # Verify fields fetched (should include customfield_10399)
        call_args = self.translator.fetch_issue_fields.call_args
        self.assertIsNotNone(call_args)
        fields_arg = call_args[0][1]
        self.assertIn("customfield_10399", fields_arg)
        self.assertNotIn("customfield_10237", fields_arg)

    def test_default_ticket_logic(self):
        """Test that other tickets default to PBB settings"""
        issue_key = "OTHER-123"
        
        self.translator.translate_issue(issue_key)
        
        # Verify glossary loading
        self.translator._load_glossary_terms.assert_called_with("pbb_glossary.json")
        
        # Verify fields fetched
        call_args = self.translator.fetch_issue_fields.call_args
        fields_arg = call_args[0][1]
        self.assertIn("customfield_10399", fields_arg)

    def test_payday_ticket_logic(self):
        """Test that PAYDAY tickets use customfield_10237 and pubg_heist_glossary.json"""
        issue_key = "PAYDAY-7"

        self.translator.translate_issue(issue_key)

        # Verify glossary loading
        self.translator._load_glossary_terms.assert_called_with("pubg_heist_glossary.json")
        self.assertEqual(self.translator.glossary_name, "PUBG Heist Royale")
        
        # Verify fields fetched (should include customfield_10237)
        call_args = self.translator.fetch_issue_fields.call_args
        self.assertIsNotNone(call_args)
        fields_arg = call_args[0][1]
        self.assertIn("customfield_10237", fields_arg)
        self.assertNotIn("customfield_10399", fields_arg)

    def test_pubgxbsg_ticket_logic(self):
        """Test that PUBGXBSG tickets use customfield_10237 and pubg_outbreak_glossary.json"""
        issue_key = "PUBGXBSG-3779"

        self.translator.translate_issue(issue_key)

        # Verify glossary loading
        self.translator._load_glossary_terms.assert_called_with("pubg_outbreak_glossary.json")
        self.assertEqual(self.translator.glossary_name, "PUBG Outbreak")
        
        # Verify fields fetched (should include customfield_10237)
        call_args = self.translator.fetch_issue_fields.call_args
        self.assertIsNotNone(call_args)
        fields_arg = call_args[0][1]
        self.assertIn("customfield_10237", fields_arg)
        self.assertNotIn("customfield_10399", fields_arg)

class TestDetermineGlossary(unittest.TestCase):
    """_determine_glossary 정적 메서드 단위 테스트"""

    def test_pubg_no_bs_tag(self):
        f, n = JiraTicketTranslator._determine_glossary("PUBG", "[v2] Some bug")
        self.assertEqual(f, "pubg_glossary.json")
        self.assertEqual(n, "PUBG")

    def test_pubg_bs_exact(self):
        f, n = JiraTicketTranslator._determine_glossary("PUBG", "[BS] Some bug")
        self.assertEqual(f, "pubg_binaryspot_glossary.json")
        self.assertEqual(n, "PUBG BinarySpot")

    def test_pubg_bs_underscore(self):
        f, n = JiraTicketTranslator._determine_glossary("PUBG", "[BS_Signoff_3] Some bug")
        self.assertEqual(f, "pubg_binaryspot_glossary.json")
        self.assertEqual(n, "PUBG BinarySpot")

    def test_pubg_bsg_not_matched(self):
        """[BSG]는 BinarySpot으로 분류되지 않아야 함"""
        f, n = JiraTicketTranslator._determine_glossary("PUBG", "[BSG] Some bug")
        self.assertEqual(f, "pubg_glossary.json")

    def test_pm_bs_underscore(self):
        f, n = JiraTicketTranslator._determine_glossary("PM", "[BS_v2] Bug report")
        self.assertEqual(f, "pubg_binaryspot_glossary.json")

    def test_pubgxbsg_always_outbreak(self):
        f, n = JiraTicketTranslator._determine_glossary("PUBGXBSG", "")
        self.assertEqual(f, "pubg_outbreak_glossary.json")
        self.assertEqual(n, "PUBG Outbreak")

    def test_payday_always_heist(self):
        f, n = JiraTicketTranslator._determine_glossary("PAYDAY", "")
        self.assertEqual(f, "pubg_heist_glossary.json")
        self.assertEqual(n, "PUBG Heist Royale")

    def test_default_pbb(self):
        f, n = JiraTicketTranslator._determine_glossary("P2", "")
        self.assertEqual(f, "pbb_glossary.json")


def _mock_createmeta_response(fields_dict):
    """createmeta API 응답을 모킹하는 헬퍼"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "projects": [{
            "issuetypes": [{
                "fields": fields_dict
            }]
        }]
    }
    return mock_resp


class TestStepsFieldDetection(unittest.TestCase):
    """Steps 필드 자동 탐지 테스트"""

    def setUp(self):
        self.client = JiraClient("https://example.com", "test@test.com", "token")
        self.client.session = MagicMock()

    def test_detect_steps_field_returns_customfield_10237(self):
        """createmeta에 customfield_10237이 있으면 해당 필드 반환"""
        self.client.session.get.return_value = _mock_createmeta_response({
            "customfield_10237": {"name": "Reproduce Steps"},
            "summary": {"name": "Summary"},
        })
        result = self.client.detect_steps_field("PUBG")
        assert result == "customfield_10237"

    def test_detect_steps_field_returns_customfield_10399(self):
        """createmeta에 customfield_10399만 있으면 해당 필드 반환"""
        self.client.session.get.return_value = _mock_createmeta_response({
            "customfield_10399": {"name": "Steps To Reproduce (STR):"},
            "summary": {"name": "Summary"},
        })
        result = self.client.detect_steps_field("P2")
        assert result == "customfield_10399"

    def test_detect_steps_field_prefers_first_candidate(self):
        """두 후보 모두 있으면 STEPS_FIELD_CANDIDATES 순서대로 첫 번째 반환"""
        self.client.session.get.return_value = _mock_createmeta_response({
            "customfield_10237": {"name": "Reproduce Steps"},
            "customfield_10399": {"name": "Steps To Reproduce (STR):"},
        })
        result = self.client.detect_steps_field("TEST")
        assert result == STEPS_FIELD_CANDIDATES[0]

    def test_detect_steps_field_by_name_unknown_customfield(self):
        """후보 ID에 없는 커스텀필드도 이름에 'step'+'reproduce' 포함되면 탐지"""
        self.client.session.get.return_value = _mock_createmeta_response({
            "customfield_99999": {"name": "Reproduce Steps (New)"},
            "summary": {"name": "Summary"},
        })
        result = self.client.detect_steps_field("NEWGAME")
        assert result == "customfield_99999"

    def test_detect_steps_field_by_name_case_insensitive(self):
        """이름 기반 탐지는 대소문자 무시"""
        self.client.session.get.return_value = _mock_createmeta_response({
            "customfield_55555": {"name": "STEPS TO REPRODUCE"},
            "summary": {"name": "Summary"},
        })
        result = self.client.detect_steps_field("ANYGAME")
        assert result == "customfield_55555"

    def test_detect_steps_field_by_name_partial_match_rejected(self):
        """'step'만 있고 'reproduce' 없으면 매칭 안 됨"""
        self.client.session.get.return_value = _mock_createmeta_response({
            "customfield_77777": {"name": "Next Steps"},
            "summary": {"name": "Summary"},
        })
        result = self.client.detect_steps_field("PARTIAL")
        assert result is None

    def test_detect_steps_field_candidates_preferred_over_name(self):
        """후보 ID와 이름 매칭 둘 다 있으면 후보 ID 우선"""
        self.client.session.get.return_value = _mock_createmeta_response({
            "customfield_10237": {"name": "Reproduce Steps"},
            "customfield_99999": {"name": "Steps to Reproduce (New)"},
        })
        result = self.client.detect_steps_field("MIXED")
        assert result == "customfield_10237"

    def test_detect_steps_field_returns_none_when_not_found(self):
        """steps 관련 필드가 전혀 없으면 None 반환"""
        self.client.session.get.return_value = _mock_createmeta_response({
            "summary": {"name": "Summary"},
            "description": {"name": "Description"},
        })
        result = self.client.detect_steps_field("UNKNOWN")
        assert result is None

    def test_detect_steps_field_caches_result(self):
        """같은 프로젝트 키로 두 번 호출 시 API 1회만 호출"""
        self.client.session.get.return_value = _mock_createmeta_response({
            "customfield_10237": {"name": "Reproduce Steps"},
        })
        self.client.detect_steps_field("PUBG")
        self.client.detect_steps_field("PUBG")
        self.client.session.get.assert_called_once()

    def test_detect_steps_field_caches_none_result(self):
        """None 결과도 캐시되어 재조회하지 않음"""
        self.client.session.get.return_value = _mock_createmeta_response({
            "summary": {"name": "Summary"},
        })
        self.client.detect_steps_field("NOPE")
        self.client.detect_steps_field("NOPE")
        self.client.session.get.assert_called_once()

    def test_detect_steps_field_different_projects_not_cached(self):
        """다른 프로젝트 키는 별도로 API 호출"""
        self.client.session.get.return_value = _mock_createmeta_response({
            "customfield_10237": {"name": "Reproduce Steps"},
        })
        self.client.detect_steps_field("PUBG")
        self.client.detect_steps_field("P2")
        assert self.client.session.get.call_count == 2

    def test_detect_steps_field_api_error_returns_none(self):
        """API 오류 시 예외 대신 None 반환"""
        self.client.session.get.side_effect = Exception("Connection error")
        result = self.client.detect_steps_field("PUBG")
        assert result is None

    def test_detect_steps_field_empty_projects(self):
        """프로젝트가 없는 응답이면 None 반환"""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"projects": []}
        self.client.session.get.return_value = mock_resp
        result = self.client.detect_steps_field("EMPTY")
        assert result is None


class TestTranslateIssueStepsDetection(unittest.TestCase):
    """translate_issue가 detect_steps_field를 사용하는지 검증"""

    def setUp(self):
        self.translator = JiraTicketTranslator(
            jira_url="https://example.com",
            email="test@example.com",
            api_token="token",
            openai_api_key="key"
        )
        self.translator.fetch_issue_fields = MagicMock(return_value={})
        self.translator._call_openai_batch = MagicMock(return_value={})
        self.translator.update_issue_fields = MagicMock()
        self.translator._load_glossary_terms = MagicMock(return_value={"term": "translation"})
        self.translator.translation_engine._load_glossary_terms = self.translator._load_glossary_terms

    def test_translate_issue_uses_detected_steps_field(self):
        """translate_issue가 detect_steps_field 결과를 사용"""
        self.translator.jira_client.detect_steps_field = MagicMock(return_value="customfield_10237")

        self.translator.translate_issue("NEWPROJ-100")

        self.translator.jira_client.detect_steps_field.assert_called_once_with("NEWPROJ")
        fields_arg = self.translator.fetch_issue_fields.call_args[0][1]
        self.assertIn("customfield_10237", fields_arg)

    def test_translate_issue_fallback_on_detection_failure(self):
        """detect_steps_field가 None이면 기존 하드코딩 fallback 사용"""
        self.translator.jira_client.detect_steps_field = MagicMock(return_value=None)

        self.translator.translate_issue("P2-999")

        # fallback: P2 → customfield_10399
        fields_arg = self.translator.fetch_issue_fields.call_args[0][1]
        self.assertIn("customfield_10399", fields_arg)

    def test_translate_issue_fallback_pubg(self):
        """detect_steps_field가 None이면 PUBG prefix에 대해 customfield_10237 fallback"""
        self.translator.jira_client.detect_steps_field = MagicMock(return_value=None)

        self.translator.translate_issue("PUBG-500")

        fields_arg = self.translator.fetch_issue_fields.call_args[0][1]
        self.assertIn("customfield_10237", fields_arg)


if __name__ == '__main__':
    unittest.main()
