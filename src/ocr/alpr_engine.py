"""
Automatic License Plate Recognition (ALPR) engine with multi-strategy enhancement.
"""

import cv2
import numpy as np
from typing import List, Tuple, Optional, Dict
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ALPREngine:
    """
    Multi-engine ALPR system with Fast-ALPR and EasyOCR fallback.
    Includes image enhancement strategies for improved accuracy.
    """

    def __init__(
        self,
        fast_alpr_enabled: bool = True,
        easyocr_enabled: bool = True,
        confidence_threshold: float = 0.5
    ):
        """
        Initialize ALPR engine.

        Args:
            fast_alpr_enabled: Enable Fast-ALPR primary engine
            easyocr_enabled: Enable EasyOCR fallback engine
            confidence_threshold: Minimum confidence for OCR results
        """
        self.fast_alpr_enabled = fast_alpr_enabled
        self.easyocr_enabled = easyocr_enabled
        self.confidence_threshold = confidence_threshold

        # Initialize engines
        self.fast_alpr = None
        self.easyocr_reader = None

        self._init_engines()

    def _init_engines(self) -> None:
        """Initialize OCR engines."""
        try:
            if self.fast_alpr_enabled:
                from fast_alpr import ALPR
                self.fast_alpr = ALPR(
                    detector_model="yolo-v9-t-384-license-plate-end2end",
                    ocr_model="global-plates-mobile-vit-v2-model"
                )
                logger.info("Fast-ALPR engine initialized")

        except ImportError:
            logger.warning("Fast-ALPR not available, using EasyOCR only")
            self.fast_alpr_enabled = False

        try:
            if self.easyocr_enabled:
                import easyocr
                self.easyocr_reader = easyocr.Reader(['en'], gpu=False)
                logger.info("EasyOCR engine initialized")

        except ImportError:
            logger.warning("EasyOCR not available")
            self.easyocr_enabled = False

    def enhance_image(self, image: np.ndarray) -> List[np.ndarray]:
        """
        Generate enhanced versions of the image for better OCR accuracy.

        Args:
            image: Input image (BGR format)

        Returns:
            List of enhanced image variants
        """
        enhanced_versions = []

        # Convert to grayscale if needed
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            gray = image.copy()

        # 1. Original
        enhanced_versions.append(('original', image))

        # 2. CLAHE (Contrast Limited Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced1 = clahe.apply(gray)
        enhanced_versions.append(('clahe', enhanced1))

        # 3. Sharpening
        kernel_sharpen = np.array([[-1, -1, -1],
                                   [-1,  9, -1],
                                   [-1, -1, -1]])
        sharpened = cv2.filter2D(gray, -1, kernel_sharpen)
        enhanced_versions.append(('sharpen', sharpened))

        # 4. Bilateral filter (noise reduction + edge preservation)
        bilateral = cv2.bilateralFilter(gray, 9, 75, 75)
        enhanced_versions.append(('bilateral', bilateral))

        # 5. Adaptive threshold
        adaptive = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            11, 2
        )
        enhanced_versions.append(('adaptive_threshold', adaptive))

        # 6. Morphological operations
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        morph = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
        enhanced_versions.append(('morphological', morph))

        return enhanced_versions

    def extract_plate_fast_alpr(
        self,
        image: np.ndarray
    ) -> Optional[Dict[str, any]]:
        """
        Extract license plate text using Fast-ALPR.

        Args:
            image: Input image

        Returns:
            Dictionary with plate text and confidence, or None
        """
        if not self.fast_alpr_enabled or self.fast_alpr is None:
            return None

        try:
            # Run Fast-ALPR
            results = self.fast_alpr.predict(image)

            if results and len(results) > 0:
                # Get the best result
                best_result = max(results, key=lambda x: x.get('confidence', 0))

                confidence = best_result.get('confidence', 0.0)
                text = best_result.get('text', '')

                if confidence >= self.confidence_threshold and text:
                    return {
                        'text': text,
                        'confidence': confidence,
                        'method': 'fast-alpr'
                    }

        except Exception as e:
            logger.debug(f"Fast-ALPR extraction failed: {e}")

        return None

    def extract_plate_easyocr(
        self,
        image: np.ndarray
    ) -> Optional[Dict[str, any]]:
        """
        Extract license plate text using EasyOCR.

        Args:
            image: Input image

        Returns:
            Dictionary with plate text and confidence, or None
        """
        if not self.easyocr_enabled or self.easyocr_reader is None:
            return None

        try:
            # Run EasyOCR
            results = self.easyocr_reader.readtext(image)

            if results and len(results) > 0:
                # Get the best result
                best_result = max(results, key=lambda x: x[2])  # x[2] is confidence

                text = best_result[1]
                confidence = best_result[2]

                if confidence >= self.confidence_threshold and text:
                    return {
                        'text': text,
                        'confidence': confidence,
                        'method': 'easyocr'
                    }

        except Exception as e:
            logger.debug(f"EasyOCR extraction failed: {e}")

        return None

    def extract_plate_optimized(
        self,
        image: np.ndarray
    ) -> Optional[Dict[str, any]]:
        """
        Extract plate using multi-strategy enhancement approach.

        Args:
            image: Input license plate image

        Returns:
            Dictionary with best OCR result
        """
        # Generate enhanced versions
        enhanced_versions = self.enhance_image(image)

        best_result = None
        best_score = 0.0

        # Try Fast-ALPR on all enhanced versions
        for strategy_name, enhanced_img in enhanced_versions:
            result = self.extract_plate_fast_alpr(enhanced_img)

            if result:
                # Score = confidence * text_length
                score = result['confidence'] * len(result['text'])

                if score > best_score:
                    best_score = score
                    best_result = result
                    best_result['enhancement'] = strategy_name

        # If Fast-ALPR didn't work, try EasyOCR on original
        if best_result is None:
            result = self.extract_plate_easyocr(image)
            if result:
                best_result = result
                best_result['enhancement'] = 'original'

        return best_result

    def process_image_file(self, image_path: str) -> Optional[Dict[str, any]]:
        """
        Process a single image file.

        Args:
            image_path: Path to image file

        Returns:
            OCR result dictionary or None
        """
        try:
            image = cv2.imread(image_path)
            if image is None:
                logger.error(f"Failed to load image: {image_path}")
                return None

            result = self.extract_plate_optimized(image)

            if result:
                result['image_path'] = image_path
                logger.info(
                    f"Extracted '{result['text']}' from {image_path} "
                    f"(confidence: {result['confidence']:.3f}, method: {result['method']})"
                )

            return result

        except Exception as e:
            logger.error(f"Error processing {image_path}: {e}")
            return None
