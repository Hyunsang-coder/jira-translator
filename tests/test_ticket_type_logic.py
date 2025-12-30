import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path to import jira_trans
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jira_trans import JiraTicketTranslator

class TestTicketTypeLogic(unittest.TestCase):
    def setUp(self):
        self.translator = JiraTicketTranslator(
            jira_url="https://example.com",
            email="test@example.com",
            api_token="token",
            openai_api_key="key"
        )
        # Mock external dependencies
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
        """Test that PAYDAY tickets use customfield_10237 and heist_glossary.json"""
        issue_key = "PAYDAY-7"
        
        self.translator.translate_issue(issue_key)
        
        # Verify glossary loading
        self.translator._load_glossary_terms.assert_called_with("heist_glossary.json")
        self.assertEqual(self.translator.glossary_name, "HeistRoyale")
        
        # Verify fields fetched (should include customfield_10237)
        call_args = self.translator.fetch_issue_fields.call_args
        self.assertIsNotNone(call_args)
        fields_arg = call_args[0][1]
        self.assertIn("customfield_10237", fields_arg)
        self.assertNotIn("customfield_10399", fields_arg)

if __name__ == '__main__':
    unittest.main()
