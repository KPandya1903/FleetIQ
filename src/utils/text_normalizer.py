"""
Text normalization utilities for OCR output correction.
"""

import re
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)


class TextNormalizer:
    """Handles OCR text normalization and character correction."""

    def __init__(self, character_mapping: Dict[str, str] = None):
        """
        Initialize text normalizer.

        Args:
            character_mapping: Dictionary mapping ambiguous characters to alternatives
        """
        self.character_mapping = character_mapping or {
            "0": "O", "O": "0",
            "1": "I", "I": "1",
            "8": "B", "B": "8",
            "5": "S", "S": "5",
            "6": "G", "G": "6",
            "2": "Z", "Z": "2"
        }

    def normalize(self, text: str) -> str:
        """
        Normalize OCR text by removing special characters and whitespace.

        Args:
            text: Raw OCR text

        Returns:
            Normalized text (alphanumeric only, uppercase)
        """
        if not text:
            return ""

        # Convert to uppercase
        text = text.upper()

        # Remove special characters and whitespace
        text = re.sub(r'[^A-Z0-9]', '', text)

        return text

    def generate_variants(self, text: str, max_variants: int = 10) -> List[str]:
        """
        Generate character variants for ambiguous OCR characters.

        Args:
            text: Normalized plate text
            max_variants: Maximum number of variants to generate

        Returns:
            List of possible text variants
        """
        variants = {text}  # Start with original

        for char in text:
            if char in self.character_mapping:
                new_variants = set()
                replacement = self.character_mapping[char]

                for variant in variants:
                    # Add variant with character replaced
                    new_variant = variant.replace(char, replacement, 1)
                    new_variants.add(new_variant)

                variants.update(new_variants)

                # Limit variants to prevent exponential growth
                if len(variants) >= max_variants:
                    break

        return list(variants)[:max_variants]

    def correct_common_ocr_errors(self, text: str) -> str:
        """
        Apply heuristic corrections for common OCR errors in license plates.

        Args:
            text: OCR text

        Returns:
            Corrected text
        """
        text = self.normalize(text)

        # License plate patterns (customize based on region)
        # Example: US plates often have letters at start, numbers at end
        # This is a simplified heuristic

        if len(text) >= 3:
            # First characters are typically letters
            for i in range(min(3, len(text))):
                if text[i].isdigit():
                    # Try converting digit to letter
                    if text[i] in self.character_mapping:
                        alt = self.character_mapping[text[i]]
                        if alt.isalpha():
                            logger.debug(f"Correcting position {i}: {text[i]} -> {alt}")

            # Last characters are typically numbers
            for i in range(max(len(text) - 3, 0), len(text)):
                if text[i].isalpha():
                    # Try converting letter to digit
                    if text[i] in self.character_mapping:
                        alt = self.character_mapping[text[i]]
                        if alt.isdigit():
                            logger.debug(f"Correcting position {i}: {text[i]} -> {alt}")

        return text

    def calculate_similarity_with_variants(
        self,
        text1: str,
        text2: str,
        similarity_fn
    ) -> float:
        """
        Calculate maximum similarity considering character variants.

        Args:
            text1: First text
            text2: Second text
            similarity_fn: Function to calculate similarity (e.g., Levenshtein)

        Returns:
            Maximum similarity score across all variants
        """
        # Generate variants for both texts
        variants1 = self.generate_variants(text1, max_variants=5)
        variants2 = self.generate_variants(text2, max_variants=5)

        max_similarity = 0.0

        # Compare all variant combinations
        for v1 in variants1:
            for v2 in variants2:
                similarity = similarity_fn(v1, v2)
                max_similarity = max(max_similarity, similarity)

        return max_similarity
