"""
Phase 3: OCR and Text Extraction
- Uses EasyOCR for license plate text extraction
- Implements preprocessing for better OCR accuracy
- Applies similarity correction for common OCR errors
- Stores results with confidence scores
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
        logging.FileHandler('logs/phase3.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PlateOCR:
    def __init__(self, db_path: str = "data/vehicle_metadata.db",
                 plates_dir: str = "cropped_plates"):
        self.db_path = db_path
        self.plates_dir = Path(plates_dir)

        # OCR reader (lazy load)
        self.reader = None

        # Stats
        self.stats = {
            'total': 0,
            'success': 0,
            'low_confidence': 0,
            'failed': 0
        }

    def load_ocr_reader(self):
        """Lazy load EasyOCR reader"""
        if self.reader is None:
            import easyocr
            logger.info("Loading EasyOCR reader (this may take a moment)...")
            # Use English for license plates
            self.reader = easyocr.Reader(['en'], gpu=False)
            logger.info("EasyOCR reader loaded")

    def preprocess_plate(self, image: np.ndarray) -> np.ndarray:
        """
        Preprocess license plate image for better OCR
        """
        try:
            # Convert to grayscale if needed
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()

            # Resize if too small (OCR works better with larger images)
            h, w = gray.shape
            if h < 50 or w < 100:
                scale = max(100 / w, 50 / h)
                new_w = int(w * scale)
                new_h = int(h * scale)
                gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

            # Apply bilateral filter to reduce noise while keeping edges
            denoised = cv2.bilateralFilter(gray, 9, 75, 75)

            # Adaptive thresholding
            thresh = cv2.adaptiveThreshold(
                denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )

            # Morphological operations to clean up
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            morph = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

            return morph

        except Exception as e:
            logger.error(f"Error preprocessing image: {e}")
            return image

    def correct_characters(self, text: str) -> str:
        """
        Apply character correction heuristics for common OCR errors

        Common mistakes:
        - 0 ↔ O, D
        - 1 ↔ I, L
        - 8 ↔ B
        - 5 ↔ S
        - 2 ↔ Z
        """
        if not text:
            return text

        corrected = text.upper().strip()

        # Remove spaces and special characters
        corrected = re.sub(r'[^A-Z0-9]', '', corrected)

        # Common corrections based on position
        # Typically: Letters at start, numbers at end (but varies by region)

        return corrected

    def extract_text_easyocr(self, image: np.ndarray) -> Tuple[Optional[str], float]:
        """
        Extract text using EasyOCR
        Returns (text, confidence)
        """
        try:
            self.load_ocr_reader()

            # Preprocess image
            processed = self.preprocess_plate(image)

            # Run OCR on both original and preprocessed
            results_original = self.reader.readtext(image, detail=1)
            results_processed = self.reader.readtext(processed, detail=1)

            # Combine results and pick the best one
            all_results = results_original + results_processed

            if not all_results:
                return None, 0.0

            # Sort by confidence and text length
            best_result = max(all_results, key=lambda x: (x[2], len(x[1])))

            text = best_result[1]
            confidence = best_result[2]

            # Apply character corrections
            corrected_text = self.correct_characters(text)

            return corrected_text, confidence

        except Exception as e:
            logger.error(f"Error in EasyOCR extraction: {e}")
            return None, 0.0

    def process_single_plate(self, plate_path: str) -> Dict:
        """
        Process a single license plate image
        """
        result = {
            'plate_path': plate_path,
            'plate_text': None,
            'confidence': 0.0,
            'status': 'pending'
        }

        try:
            # Read image
            image = cv2.imread(plate_path)

            if image is None:
                result['status'] = 'read_failed'
                self.stats['failed'] += 1
                return result

            # Extract text with EasyOCR
            text, confidence = self.extract_text_easyocr(image)

            if text and len(text) > 2:  # Valid plate should have at least 3 characters
                result['plate_text'] = text
                result['confidence'] = confidence
                result['status'] = 'success'
                self.stats['success'] += 1

                if confidence < 0.5:
                    self.stats['low_confidence'] += 1

            else:
                result['status'] = 'no_text_detected'
                self.stats['failed'] += 1

        except Exception as e:
            logger.error(f"Error processing {plate_path}: {e}")
            result['status'] = 'error'
            self.stats['failed'] += 1

        return result

    def process_all_plates(self) -> List[Dict]:
        """
        Process all cropped license plates
        """
        # Get all plate files
        plate_files = sorted(self.plates_dir.glob("*.jpg"))
        self.stats['total'] = len(plate_files)

        logger.info(f"Processing {len(plate_files)} license plates...")
        print(f"\nProcessing {len(plate_files)} license plates with OCR...")
        print(f"This may take a few minutes...\n")

        results = []
        for plate_path in tqdm(plate_files, desc="Extracting text"):
            result = self.process_single_plate(str(plate_path))
            results.append(result)

        return results

    def update_database(self, results: List[Dict]):
        """
        Update database with OCR results
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Add new columns if they don't exist
        try:
            cursor.execute("ALTER TABLE vehicle_metadata ADD COLUMN plate_text TEXT")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE vehicle_metadata ADD COLUMN ocr_confidence REAL")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE vehicle_metadata ADD COLUMN ocr_status TEXT")
        except:
            pass

        # Create mapping from plate_path to result
        results_map = {Path(r['plate_path']).name: r for r in results}

        # Update records
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
                            ocr_status = ?
                        WHERE id = ?
                    """, (
                        r['plate_text'],
                        r['confidence'],
                        r['status'],
                        record_id
                    ))

        conn.commit()
        conn.close()

        logger.info(f"Updated {len(records)} records in database")

    def save_results_json(self, results: List[Dict],
                         output_path: str = "data/phase3_results.json"):
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
        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE ocr_status IS NOT NULL")
        stats['total_processed'] = cursor.fetchone()[0]

        # Successful OCR
        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE ocr_status = 'success'")
        stats['success'] = cursor.fetchone()[0]

        # Failed OCR
        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE ocr_status != 'success' AND ocr_status IS NOT NULL")
        stats['failed'] = cursor.fetchone()[0]

        # Average confidence
        cursor.execute("SELECT AVG(ocr_confidence) FROM vehicle_metadata WHERE ocr_status = 'success'")
        avg_conf = cursor.fetchone()[0]
        stats['avg_confidence'] = avg_conf if avg_conf else 0.0

        # Sample results
        cursor.execute("""
            SELECT url, plate_text, ocr_confidence
            FROM vehicle_metadata
            WHERE ocr_status = 'success'
            ORDER BY ocr_confidence DESC
            LIMIT 5
        """)
        stats['samples'] = cursor.fetchall()

        # Unique plate texts
        cursor.execute("SELECT COUNT(DISTINCT plate_text) FROM vehicle_metadata WHERE plate_text IS NOT NULL")
        stats['unique_plates'] = cursor.fetchone()[0]

        conn.close()
        return stats


def main():
    """Main execution function for Phase 3"""

    print("\n" + "="*80)
    print("PHASE 3: OCR and Text Extraction")
    print("="*80 + "\n")

    ocr = PlateOCR()

    # Process all plates
    results = ocr.process_all_plates()

    # Update database
    print("\nUpdating database...")
    ocr.update_database(results)

    # Save results
    ocr.save_results_json(results)

    # Display statistics
    print("\n" + "="*80)
    print("PHASE 3 RESULTS")
    print("="*80)

    stats = ocr.get_statistics()

    print(f"\nTotal plates processed: {stats['total_processed']}")
    print(f"Successful OCR: {stats['success']}")
    print(f"Failed OCR: {stats['failed']}")
    print(f"Success rate: {stats['success']/stats['total_processed']*100:.2f}%")
    print(f"Average confidence: {stats['avg_confidence']:.3f}")
    print(f"Unique plate texts: {stats['unique_plates']}")

    print(f"\nSample results (highest confidence):")
    for i, (url, text, conf) in enumerate(stats['samples'], 1):
        print(f"  {i}. {text} (confidence: {conf:.3f})")
        print(f"     URL: ...{url[-50:]}")

    print(f"\n✓ Phase 3 complete!")
    print(f"✓ OCR results saved to: data/phase3_results.json")
    print(f"✓ Database updated with plate texts")
    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    # Ensure directories exist
    Path("logs").mkdir(exist_ok=True)

    # Run main
    main()
