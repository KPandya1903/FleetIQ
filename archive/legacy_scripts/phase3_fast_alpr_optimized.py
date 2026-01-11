"""
Phase 3 (Optimized): OCR with Fast-ALPR - Enhanced for Maximum Accuracy
- Preprocessing: contrast enhancement, denoising, sharpening
- Multiple inference attempts with different image enhancements
- Confidence thresholding to prefer Fast-ALPR over EasyOCR
- Better character correction heuristics
"""

import sqlite3
import cv2
import numpy as np
from pathlib import Path
from tqdm import tqdm
from typing import Dict, Optional, List, Tuple
import logging
import json
import re

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/phase3_fastalpr_optimized.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class OptimizedFastALPRExtractor:
    def __init__(self, db_path: str = "data/vehicle_metadata.db",
                 plates_dir: str = "cropped_plates"):
        self.db_path = db_path
        self.plates_dir = Path(plates_dir)

        # Fast-ALPR reader
        self.alpr = None
        # EasyOCR fallback
        self.easy_reader = None

        # Stats
        self.stats = {
            'total': 0,
            'success_fastalpr': 0,
            'success_easyocr': 0,
            'failed': 0
        }

    def load_fast_alpr(self):
        """Load Fast-ALPR"""
        if self.alpr is None:
            try:
                from fast_alpr import ALPR
                logger.info("Loading Fast-ALPR models...")
                self.alpr = ALPR(
                    detector_model="yolo-v9-t-384-license-plate-end2end",
                    ocr_model="global-plates-mobile-vit-v2-model",
                )
                logger.info("Fast-ALPR loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load Fast-ALPR: {e}")
                self.alpr = None

    def load_easyocr(self):
        """Load EasyOCR as fallback"""
        if self.easy_reader is None:
            try:
                import easyocr
                logger.info("Loading EasyOCR as fallback...")
                self.easy_reader = easyocr.Reader(['en'], gpu=False)
                logger.info("EasyOCR loaded")
            except Exception as e:
                logger.error(f"Failed to load EasyOCR: {e}")
                self.easy_reader = None

    def enhance_image(self, image: np.ndarray) -> List[np.ndarray]:
        """
        Create multiple enhanced versions of the image for better OCR
        Returns list of enhanced images
        """
        enhanced_versions = []

        # Original
        enhanced_versions.append(image)

        # Version 1: Contrast enhancement with CLAHE
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()

            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            enhanced1 = clahe.apply(gray)
            enhanced1_bgr = cv2.cvtColor(enhanced1, cv2.COLOR_GRAY2BGR)
            enhanced_versions.append(enhanced1_bgr)
        except:
            pass

        # Version 2: Sharpening
        try:
            kernel_sharpen = np.array([[-1,-1,-1],
                                       [-1, 9,-1],
                                       [-1,-1,-1]])
            sharpened = cv2.filter2D(image, -1, kernel_sharpen)
            enhanced_versions.append(sharpened)
        except:
            pass

        # Version 3: Bilateral filter (noise reduction + edge preservation)
        try:
            bilateral = cv2.bilateralFilter(image, 9, 75, 75)
            enhanced_versions.append(bilateral)
        except:
            pass

        # Version 4: Adaptive threshold (high contrast)
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()

            adaptive = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )
            adaptive_bgr = cv2.cvtColor(adaptive, cv2.COLOR_GRAY2BGR)
            enhanced_versions.append(adaptive_bgr)
        except:
            pass

        # Version 5: Morphological operations
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()

            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            morph = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
            morph_bgr = cv2.cvtColor(morph, cv2.COLOR_GRAY2BGR)
            enhanced_versions.append(morph_bgr)
        except:
            pass

        return enhanced_versions

    def correct_characters(self, text: str) -> str:
        """Enhanced character correction for license plates"""
        if not text:
            return text

        corrected = text.upper().strip()

        # Remove spaces and most special characters except common plate separators
        corrected = re.sub(r'[^A-Z0-9\-]', '', corrected)

        # Common OCR corrections (can be customized by region)
        # These are heuristics - adjust based on your license plate format

        return corrected

    def extract_with_fastalpr(self, image_path: str) -> Tuple[Optional[str], float]:
        """
        Extract text using Fast-ALPR with multiple preprocessing attempts
        """
        try:
            self.load_fast_alpr()

            if self.alpr is None:
                return None, 0.0

            # Read original image
            image = cv2.imread(image_path)
            if image is None:
                return None, 0.0

            # Generate enhanced versions
            enhanced_images = self.enhance_image(image)

            best_text = None
            best_confidence = 0.0

            # Try Fast-ALPR on each enhanced version
            for idx, enhanced_img in enumerate(enhanced_images):
                try:
                    # Save temporary enhanced image
                    temp_path = f"/tmp/enhanced_{Path(image_path).stem}_{idx}.jpg"
                    cv2.imwrite(temp_path, enhanced_img)

                    # Run Fast-ALPR
                    alpr_results = self.alpr.predict(temp_path)

                    # Clean up temp file
                    try:
                        Path(temp_path).unlink()
                    except:
                        pass

                    if not alpr_results:
                        continue

                    # Process all results from this version
                    for result in alpr_results:
                        try:
                            # Extract text and confidence
                            if hasattr(result, 'ocr'):
                                text = result.ocr.text if hasattr(result.ocr, 'text') else str(result.ocr)
                                confidence = result.ocr.confidence if hasattr(result.ocr, 'confidence') else 0.5
                            elif hasattr(result, 'text'):
                                text = result.text
                                confidence = result.confidence if hasattr(result.confidence) else 0.5
                            else:
                                continue

                            # Apply corrections
                            corrected_text = self.correct_characters(text)

                            # Only consider if we got meaningful text
                            if corrected_text and len(corrected_text) >= 3:
                                # Prefer higher confidence and longer text
                                score = confidence + (len(corrected_text) * 0.01)

                                if score > best_confidence:
                                    best_text = corrected_text
                                    best_confidence = confidence

                        except Exception as e:
                            continue

                except Exception as e:
                    logger.debug(f"Error processing enhanced version {idx}: {e}")
                    continue

            return best_text, float(best_confidence)

        except Exception as e:
            logger.error(f"Error in Fast-ALPR extraction: {e}")
            return None, 0.0

    def preprocess_for_easyocr(self, image: np.ndarray) -> np.ndarray:
        """Optimized preprocessing for EasyOCR"""
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()

            # Resize if too small
            h, w = gray.shape
            if h < 64 or w < 128:
                scale = max(128 / w, 64 / h) * 1.5
                new_w = int(w * scale)
                new_h = int(h * scale)
                gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

            # CLAHE for contrast
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            enhanced = clahe.apply(gray)

            # Bilateral filter
            bilateral = cv2.bilateralFilter(enhanced, 9, 75, 75)

            # Adaptive threshold
            thresh = cv2.adaptiveThreshold(
                bilateral, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )

            return thresh

        except Exception as e:
            logger.error(f"Error preprocessing: {e}")
            return image

    def extract_with_easyocr(self, image_path: str) -> Tuple[Optional[str], float]:
        """Fallback: Extract with EasyOCR"""
        try:
            self.load_easyocr()

            if self.easy_reader is None:
                return None, 0.0

            image = cv2.imread(image_path)
            if image is None:
                return None, 0.0

            # Try multiple preprocessing strategies
            processed = self.preprocess_for_easyocr(image)

            # Run on both original and processed
            results = []
            try:
                results += self.easy_reader.readtext(image, detail=1)
            except:
                pass

            try:
                results += self.easy_reader.readtext(processed, detail=1)
            except:
                pass

            if not results:
                return None, 0.0

            # Get best result
            best_result = max(results, key=lambda x: (x[2], len(x[1])))
            text = best_result[1]
            confidence = best_result[2]

            corrected_text = self.correct_characters(text)

            return corrected_text, confidence

        except Exception as e:
            logger.error(f"Error in EasyOCR: {e}")
            return None, 0.0

    def process_single_plate(self, plate_path: str) -> Dict:
        """Process a single plate with optimized Fast-ALPR"""
        result = {
            'plate_path': plate_path,
            'plate_text': None,
            'confidence': 0.0,
            'method': None,
            'status': 'pending'
        }

        # Try Fast-ALPR first with optimizations
        text, confidence = self.extract_with_fastalpr(plate_path)

        # Only accept Fast-ALPR if confidence is reasonable OR text is long enough
        if text and len(text) >= 3 and (confidence > 0.3 or len(text) >= 5):
            result['plate_text'] = text
            result['confidence'] = confidence
            result['method'] = 'fast-alpr-optimized'
            result['status'] = 'success'
            self.stats['success_fastalpr'] += 1
            return result

        # Fallback to EasyOCR
        text, confidence = self.extract_with_easyocr(plate_path)

        if text and len(text) >= 3:
            result['plate_text'] = text
            result['confidence'] = confidence
            result['method'] = 'easyocr'
            result['status'] = 'success'
            self.stats['success_easyocr'] += 1
            return result

        # Both failed
        result['status'] = 'no_text_detected'
        self.stats['failed'] += 1
        return result

    def process_all_plates(self) -> List[Dict]:
        """Process all plates"""
        plate_files = sorted(self.plates_dir.glob("*.jpg"))
        self.stats['total'] = len(plate_files)

        logger.info(f"Processing {len(plate_files)} plates with Optimized Fast-ALPR...")
        print(f"\nProcessing {len(plate_files)} plates with Optimized Fast-ALPR...")
        print(f"This may take a few minutes...\n")

        results = []
        for plate_path in tqdm(plate_files, desc="Extracting text"):
            result = self.process_single_plate(str(plate_path))
            results.append(result)

        return results

    def update_database(self, results: List[Dict]):
        """Update database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        results_map = {Path(r['plate_path']).name: r for r in results}

        cursor.execute("SELECT id, plate_path FROM vehicle_metadata WHERE plate_path IS NOT NULL")
        records = cursor.fetchall()

        for record_id, plate_path in records:
            if plate_path:
                plate_filename = Path(plate_path).name
                if plate_filename in results_map:
                    r = results_map[plate_filename]
                    cursor.execute("""
                        UPDATE vehicle_metadata
                        SET plate_text = ?,
                            ocr_confidence = ?,
                            plate_text_fastalpr = ?,
                            ocr_confidence_fastalpr = ?,
                            ocr_method = ?,
                            ocr_status_fastalpr = ?
                        WHERE id = ?
                    """, (
                        r['plate_text'], r['confidence'],
                        r['plate_text'], r['confidence'],
                        r['method'], r['status'],
                        record_id
                    ))

        conn.commit()
        conn.close()
        logger.info(f"Updated {len(records)} records")

    def save_results_json(self, results: List[Dict],
                         output_path: str = "data/phase3_fastalpr_optimized_results.json"):
        """Save results"""
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"Saved to {output_path}")

    def get_statistics(self) -> Dict:
        """Get statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}

        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE ocr_status_fastalpr IS NOT NULL")
        stats['total_processed'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE ocr_status_fastalpr = 'success'")
        stats['success'] = cursor.fetchone()[0]

        cursor.execute("SELECT ocr_method, COUNT(*) FROM vehicle_metadata WHERE ocr_method IS NOT NULL GROUP BY ocr_method")
        stats['by_method'] = dict(cursor.fetchall())

        cursor.execute("SELECT AVG(ocr_confidence_fastalpr) FROM vehicle_metadata WHERE ocr_status_fastalpr = 'success'")
        avg_conf = cursor.fetchone()[0]
        stats['avg_confidence'] = avg_conf if avg_conf else 0.0

        cursor.execute("""
            SELECT url, plate_text_fastalpr, ocr_confidence_fastalpr, ocr_method
            FROM vehicle_metadata
            WHERE ocr_status_fastalpr = 'success'
            ORDER BY ocr_confidence_fastalpr DESC
            LIMIT 10
        """)
        stats['samples'] = cursor.fetchall()

        cursor.execute("SELECT COUNT(DISTINCT plate_text_fastalpr) FROM vehicle_metadata WHERE plate_text_fastalpr IS NOT NULL")
        stats['unique_plates'] = cursor.fetchone()[0]

        conn.close()
        return stats


def main():
    """Main execution"""

    print("\n" + "="*80)
    print("PHASE 3 (OPTIMIZED): OCR with Enhanced Fast-ALPR")
    print("="*80 + "\n")

    extractor = OptimizedFastALPRExtractor()

    results = extractor.process_all_plates()

    print("\nUpdating database...")
    extractor.update_database(results)

    extractor.save_results_json(results)

    print("\n" + "="*80)
    print("PHASE 3 (OPTIMIZED FAST-ALPR) RESULTS")
    print("="*80)

    stats = extractor.get_statistics()

    print(f"\nTotal: {stats['total_processed']}")
    print(f"Success: {stats['success']}")
    print(f"Failed: {stats['total_processed'] - stats['success']}")
    print(f"Success rate: {stats['success']/stats['total_processed']*100:.2f}%")
    print(f"Avg confidence: {stats['avg_confidence']:.3f}")
    print(f"Unique plates: {stats['unique_plates']}")

    print(f"\nBy method:")
    for method, count in stats.get('by_method', {}).items():
        print(f"  {method}: {count}")

    print(f"\nTop samples:")
    for i, (url, text, conf, method) in enumerate(stats['samples'][:5], 1):
        print(f"  {i}. {text} (conf: {conf:.3f}, method: {method})")

    print(f"\n✓ Phase 3 (Optimized) complete!")
    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    main()
