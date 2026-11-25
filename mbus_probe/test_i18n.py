import unittest
from i18n import resolve_language, LANGUAGES

class LanguageTests(unittest.TestCase):
    def test_explicit(self):
        for language in LANGUAGES:
            self.assertEqual(resolve_language(language, "de"), language)

    def test_browser(self):
        self.assertEqual(resolve_language("auto", "fr;q=1,nn;q=0.9,de;q=0.8"), "nn-NO")
        self.assertEqual(resolve_language("auto", "de;q=0,en;q=0.5"), "en-GB")
        self.assertEqual(resolve_language("auto", "nb-NO"), "nb-NO")

    def test_fallback(self):
        for language in ("fr", "", None):
            self.assertEqual(resolve_language(language), "en-GB")
        self.assertEqual(resolve_language("auto", "fr,*;q=0.1"), "en-GB")
