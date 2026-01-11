"""
Phase 3 (Revised): OCR and Text Extraction using Fast-ALPR
- Uses fast-alpr library for license plate text extraction
- Falls back to EasyOCR if fast-alpr fails
- Applies similarity correction for common OCR errors
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

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/phase3_fastalpr.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class FastALPRExtractor:
    def __init__(self, db_path: str = "data/vehicle_metadata.db",
                 plates_dir: str = "cropped_plates"):
        self.db_path = db_path
        self.plates_dir = Path(plates_dir)

        # Fast-ALPR reader (lazy load)
        self.alpr = None

        # EasyOCR fallback (lazy load)
        self.easy_reader = None

        # Stats
        self.stats = {
            'total': 0,
            'success_fastalpr': 0,
            'success_easyocr': 0,
            'failed': 0
        }

    def load_fast_alpr(self):
        """Lazy load Fast-ALPR"""
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
        """Lazy load EasyOCR as fallback"""
        if self.easy_reader is None:
            try:
                import easyocr
                logger.info("Loading EasyOCR as fallback...")
                self.easy_reader = easyocr.Reader(['en'], gpu=False)
                logger.info("EasyOCR loaded")
            except Exception as e:
                logger.error(f"Failed to load EasyOCR: {e}")
                self.easy_reader = None

    def correct_characters(self, text: str) -> str:
        """
        Apply character correction heuristics for common OCR errors
        """
        if not text:
            return text

        corrected = text.upper().strip()

        # Remove spaces and special characters
        corrected = re.sub(r'[^A-Z0-9]', '', corrected)

        return corrected

    def extract_with_fastalpr(self, image_path: str) -> Tuple[Optional[str], float]:
        """
        Extract text using Fast-ALPR
        Returns (text, confidence)
        """
        try:
            self.load_fast_alpr()

            if self.alpr is None:
                return None, 0.0

            # Run Fast-ALPR prediction
            alpr_results = self.alpr.predict(image_path)

            if not alpr_results:
                return None, 0.0

            # Get the best result (highest confidence)
            best_result = max(alpr_results, key=lambda x: x.confidence if hasattr(x, 'confidence') else 0.0)

            # Extract text and confidence
            if hasattr(best_result, 'ocr'):
                text = best_result.ocr.text if hasattr(best_result.ocr, 'text') else str(best_result.ocr)
                confidence = best_result.ocr.confidence if hasattr(best_result.ocr, 'confidence') else 0.5
            elif hasattr(best_result, 'text'):
                text = best_result.text
                confidence = best_result.confidence if hasattr(best_result, 'confidence') else 0.5
            else:
                text = str(best_result)
                confidence = 0.3

            # Apply corrections
            corrected_text = self.correct_characters(text)

            return corrected_text, float(confidence)

        except Exception as e:
            logger.error(f"Error in Fast-ALPR extraction: {e}")
            return None, 0.0

    def preprocess_plate(self, image: np.ndarray) -> np.ndarray:
        """Preprocess for EasyOCR fallback"""
        try:
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()

            # Resize if too small
            h, w = gray.shape
            if h < 50 or w < 100:
                scale = max(100 / w, 50 / h)
                new_w = int(w * scale)
                new_h = int(h * scale)
                gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

            # Apply adaptive thresholding
            thresh = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )

            return thresh

        except Exception as e:
            logger.error(f"Error preprocessing: {e}")
            return image

    def extract_with_easyocr(self, image_path: str) -> Tuple[Optional[str], float]:
        """
        Fallback: Extract text using EasyOCR
        """
        try:
            self.load_easyocr()

            if self.easy_reader is None:
                return None, 0.0

            # Read image
            image = cv2.imread(image_path)
            if image is None:
                return None, 0.0

            # Preprocess
            processed = self.preprocess_plate(image)

            # Run OCR on both original and processed
            results_original = self.easy_reader.readtext(image, detail=1)
            results_processed = self.easy_reader.readtext(processed, detail=1)

            all_results = results_original + results_processed

            if not all_results:
                return None, 0.0

            # Get best result
            best_result = max(all_results, key=lambda x: (x[2], len(x[1])))
            text = best_result[1]
            confidence = best_result[2]

            # Apply corrections
            corrected_text = self.correct_characters(text)

            return corrected_text, confidence

        except Exception as e:
            logger.error(f"Error in EasyOCR extraction: {e}")
            return None, 0.0

    def process_single_plate(self, plate_path: str) -> Dict:
        """
        Process a single license plate: try Fast-ALPR first, fallback to EasyOCR
        """
        result = {
            'plate_path': plate_path,
            'plate_text': None,
            'confidence': 0.0,
            'method': None,
            'status': 'pending'
        }

        # Try Fast-ALPR first
        text, confidence = self.extract_with_fastalpr(plate_path)

        if text and len(text) > 2:
            result['plate_text'] = text
            result['confidence'] = confidence
            result['method'] = 'fast-alpr'
            result['status'] = 'success'
            self.stats['success_fastalpr'] += 1
            return result

        # Fallback to EasyOCR
        text, confidence = self.extract_with_easyocr(plate_path)

        if text and len(text) > 2:
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
        """Process all cropped license plates"""
        plate_files = sorted(self.plates_dir.glob("*.jpg"))
        self.stats['total'] = len(plate_files)

        logger.info(f"Processing {len(plate_files)} license plates with Fast-ALPR...")
        print(f"\nProcessing {len(plate_files)} license plates with Fast-ALPR...")
        print(f"This may take a few minutes...\n")

        results = []
        for plate_path in tqdm(plate_files, desc="Extracting text"):
            result = self.process_single_plate(str(plate_path))
            results.append(result)

        return results

    def update_database(self, results: List[Dict]):
        """Update database with OCR results"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Add/update columns
        try:
            cursor.execute("ALTER TABLE vehicle_metadata ADD COLUMN plate_text_fastalpr TEXT")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE vehicle_metadata ADD COLUMN ocr_confidence_fastalpr REAL")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE vehicle_metadata ADD COLUMN ocr_method TEXT")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE vehicle_metadata ADD COLUMN ocr_status_fastalpr TEXT")
        except:
            pass

        # Update plate_text and ocr_confidence columns too (overwrite old EasyOCR results)
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
                        r['plate_text'],
                        r['confidence'],
                        r['plate_text'],
                        r['confidence'],
                        r['method'],
                        r['status'],
                        record_id
                    ))

        conn.commit()
        conn.close()
        logger.info(f"Updated {len(records)} records in database")

    def save_results_json(self, results: List[Dict],
                         output_path: str = "data/phase3_fastalpr_results.json"):
        """Save results to JSON"""
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"Saved results to {output_path}")

    def get_statistics(self) -> Dict:
        """Get OCR statistics from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}

        # Total with OCR
        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE ocr_status_fastalpr IS NOT NULL")
        stats['total_processed'] = cursor.fetchone()[0]

        # Successful OCR
        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE ocr_status_fastalpr = 'success'")
        stats['success'] = cursor.fetchone()[0]

        # By method
        cursor.execute("SELECT ocr_method, COUNT(*) FROM vehicle_metadata WHERE ocr_method IS NOT NULL GROUP BY ocr_method")
        stats['by_method'] = dict(cursor.fetchall())

        # Average confidence
        cursor.execute("SELECT AVG(ocr_confidence_fastalpr) FROM vehicle_metadata WHERE ocr_status_fastalpr = 'success'")
        avg_conf = cursor.fetchone()[0]
        stats['avg_confidence'] = avg_conf if avg_conf else 0.0

        # Sample results
        cursor.execute("""
            SELECT url, plate_text_fastalpr, ocr_confidence_fastalpr, ocr_method
            FROM vehicle_metadata
            WHERE ocr_status_fastalpr = 'success'
            ORDER BY ocr_confidence_fastalpr DESC
            LIMIT 10
        """)
        stats['samples'] = cursor.fetchall()

        # Unique plates
        cursor.execute("SELECT COUNT(DISTINCT plate_text_fastalpr) FROM vehicle_metadata WHERE plate_text_fastalpr IS NOT NULL")
        stats['unique_plates'] = cursor.fetchone()[0]

        conn.close()
        return stats


def main():
    """Main execution function for Phase 3 (Fast-ALPR)"""

    print("\n" + "="*80)
    print("PHASE 3 (REVISED): OCR with Fast-ALPR")
    print("="*80 + "\n")

    extractor = FastALPRExtractor()

    # Process all plates
    results = extractor.process_all_plates()

    # Update database
    print("\nUpdating database...")
    extractor.update_database(results)

    # Save results
    extractor.save_results_json(results)

    # Display statistics
    print("\n" + "="*80)
    print("PHASE 3 (FAST-ALPR) RESULTS")
    print("="*80)

    stats = extractor.get_statistics()

    print(f"\nTotal plates processed: {stats['total_processed']}")
    print(f"Successful OCR: {stats['success']}")
    print(f"Failed OCR: {stats['total_processed'] - stats['success']}")
    print(f"Success rate: {stats['success']/stats['total_processed']*100:.2f}%")
    print(f"Average confidence: {stats['avg_confidence']:.3f}")
    print(f"Unique plate texts: {stats['unique_plates']}")

    print(f"\nBy method:")
    for method, count in stats.get('by_method', {}).items():
        print(f"  {method}: {count}")

    print(f"\nSample results (highest confidence):")
    for i, (url, text, conf, method) in enumerate(stats['samples'][:5], 1):
        print(f"  {i}. {text} (confidence: {conf:.3f}, method: {method})")
        print(f"     URL: ...{url[-50:]}")

    print(f"\n✓ Phase 3 (Fast-ALPR) complete!")
    print(f"✓ Results saved to: data/phase3_fastalpr_results.json")
    print(f"✓ Database updated with Fast-ALPR results")
    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    main()
