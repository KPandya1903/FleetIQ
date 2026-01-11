"""
Unit tests for text normalization utilities.
"""

import unittest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.text_normalizer import TextNormalizer


class TestTextNormalizer(unittest.TestCase):
    """Test cases for TextNormalizer class."""

    def setUp(self):
        """Set up test fixtures."""
        self.normalizer = TextNormalizer()

    def test_normalize_basic(self):
        """Test basic text normalization."""
        result = self.normalizer.normalize("ABC-123")
        self.assertEqual(result, "ABC123")

    def test_normalize_lowercase(self):
        """Test lowercase conversion."""
        result = self.normalizer.normalize("abc123")
        self.assertEqual(result, "ABC123")

    def test_normalize_special_characters(self):
        """Test removal of special characters."""
        result = self.normalizer.normalize("AB C-1_23!")
        self.assertEqual(result, "ABC123")

    def test_normalize_empty(self):
        """Test empty string."""
        result = self.normalizer.normalize("")
        self.assertEqual(result, "")

    def test_normalize_none(self):
        """Test None input."""
        result = self.normalizer.normalize(None)
        self.assertEqual(result, "")

    def test_generate_variants(self):
        """Test variant generation for ambiguous characters."""
        variants = self.normalizer.generate_variants("ABC123")

        # Should include original
        self.assertIn("ABC123", variants)

        # Should include some variants (e.g., O instead of 0)
        # Note: specific variants depend on character mapping

    def test_generate_variants_limit(self):
        """Test variant generation with limit."""
        variants = self.normalizer.generate_variants("ABCD1234", max_variants=3)

        # Should not exceed max
        self.assertLessEqual(len(variants), 3)

    def test_correct_common_ocr_errors(self):
        """Test OCR error correction."""
        # This is heuristic-based, so we just check it doesn't crash
        result = self.normalizer.correct_common_ocr_errors("ABC123")
        self.assertIsInstance(result, str)


class TestCharacterVariants(unittest.TestCase):
    """Test character variant generation."""

    def setUp(self):
        """Set up test fixtures."""
        self.normalizer = TextNormalizer()

    def test_zero_oh_variants(self):
        """Test 0/O character variants."""
        variants = self.normalizer.generate_variants("A0B")

        # Should have variant with O
        self.assertTrue(
            any('O' in v for v in variants),
            "Should generate O variant for 0"
        )

    def test_one_i_variants(self):
        """Test 1/I character variants."""
        variants = self.normalizer.generate_variants("A1B")

        # Should have variant with I
        self.assertTrue(
            any('I' in v for v in variants),
            "Should generate I variant for 1"
        )


if __name__ == '__main__':
    unittest.main()
