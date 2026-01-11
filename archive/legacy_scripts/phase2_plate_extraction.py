"""
Phase 2: License Plate Extraction
- Downloads images asynchronously
- Crops plates using metadata bbox (1997 images)
- Falls back to YOLO detection for 3 images without bbox
"""

import asyncio
import aiohttp
import sqlite3
import cv2
import numpy as np
from pathlib import Path
from PIL import Image
from io import BytesIO
from tqdm.asyncio import tqdm
from typing import Dict, Optional, Tuple
import logging
import json

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/phase2.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PlateExtractor:
    def __init__(self, db_path: str = "data/vehicle_metadata.db",
                 output_dir: str = "cropped_plates"):
        self.db_path = db_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

        # Stats
        self.stats = {
            'total': 0,
            'success_bbox': 0,
            'success_yolo': 0,
            'failed': 0,
            'skipped': 0
        }

        # YOLO model (lazy load)
        self.yolo_model = None

    def get_all_records(self):
        """Get all records from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, url, bbox_x, bbox_y, bbox_w, bbox_h
            FROM vehicle_metadata
            ORDER BY id
        """)

        records = cursor.fetchall()
        conn.close()

        return records

    async def download_image(self, session: aiohttp.ClientSession,
                            url: str) -> Optional[np.ndarray]:
        """Download image and convert to numpy array"""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status != 200:
                    logger.error(f"Failed to download {url}: Status {response.status}")
                    return None

                image_data = await response.read()

                # Convert to PIL Image then to numpy array
                image = Image.open(BytesIO(image_data))
                image_np = np.array(image)

                # Convert RGB to BGR for OpenCV
                if len(image_np.shape) == 3 and image_np.shape[2] == 3:
                    image_np = cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR)

                return image_np

        except asyncio.TimeoutError:
            logger.error(f"Timeout downloading {url}")
            return None
        except Exception as e:
            logger.error(f"Error downloading {url}: {e}")
            return None

    def crop_with_bbox(self, image: np.ndarray,
                       bbox_x: float, bbox_y: float,
                       bbox_w: float, bbox_h: float) -> Optional[np.ndarray]:
        """Crop image using bounding box coordinates"""
        try:
            x, y, w, h = int(bbox_x), int(bbox_y), int(bbox_w), int(bbox_h)

            # Validate coordinates
            img_h, img_w = image.shape[:2]

            if x < 0 or y < 0 or x + w > img_w or y + h > img_h:
                logger.warning(f"Invalid bbox: ({x},{y},{w},{h}) for image size ({img_w},{img_h})")
                # Clip to image boundaries
                x = max(0, min(x, img_w - 1))
                y = max(0, min(y, img_h - 1))
                w = min(w, img_w - x)
                h = min(h, img_h - y)

            cropped = image[y:y+h, x:x+w]

            if cropped.size == 0:
                logger.error("Cropped image is empty")
                return None

            return cropped

        except Exception as e:
            logger.error(f"Error cropping with bbox: {e}")
            return None

    def detect_plate_with_yolo(self, image: np.ndarray) -> Optional[np.ndarray]:
        """Detect and crop license plate using YOLO"""
        try:
            # Lazy load YOLO model
            if self.yolo_model is None:
                from ultralytics import YOLO
                logger.info("Loading YOLO model...")
                # Use YOLOv8 pretrained on license plates or general detection
                # For now, we'll use a general model and look for rectangular objects
                # In production, you'd use a license-plate-specific model
                self.yolo_model = YOLO('yolov8n.pt')  # Nano model for speed
                logger.info("YOLO model loaded")

            # Run detection
            results = self.yolo_model(image, verbose=False)

            # Look for detections (we'll take the largest rectangular detection)
            best_plate = None
            best_area = 0

            for result in results:
                boxes = result.boxes
                for box in boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    area = (x2 - x1) * (y2 - y1)

                    # Filter by aspect ratio (license plates are wider than tall)
                    width = x2 - x1
                    height = y2 - y1
                    aspect_ratio = width / height if height > 0 else 0

                    if 1.5 < aspect_ratio < 5.0 and area > best_area:
                        best_area = area
                        best_plate = image[y1:y2, x1:x2]

            if best_plate is not None:
                logger.info(f"YOLO detected plate with area {best_area}")
                return best_plate
            else:
                logger.warning("YOLO failed to detect license plate")
                return None

        except Exception as e:
            logger.error(f"Error in YOLO detection: {e}")
            return None

    async def process_single_image(self, session: aiohttp.ClientSession,
                                   record: Tuple) -> Dict:
        """Process a single image: download and crop"""
        record_id, url, bbox_x, bbox_y, bbox_w, bbox_h = record

        result = {
            'id': record_id,
            'url': url,
            'status': 'pending',
            'method': None,
            'plate_path': None
        }

        # Download image
        image = await self.download_image(session, url)
        if image is None:
            result['status'] = 'download_failed'
            self.stats['failed'] += 1
            return result

        # Determine cropping method
        cropped_plate = None

        if bbox_x is not None:
            # Method 1: Use metadata bbox
            cropped_plate = self.crop_with_bbox(image, bbox_x, bbox_y, bbox_w, bbox_h)
            if cropped_plate is not None:
                result['method'] = 'bbox'
                self.stats['success_bbox'] += 1
            else:
                logger.warning(f"Bbox crop failed for {url}, trying YOLO")

        if cropped_plate is None:
            # Method 2: Fall back to YOLO
            cropped_plate = self.detect_plate_with_yolo(image)
            if cropped_plate is not None:
                result['method'] = 'yolo'
                self.stats['success_yolo'] += 1
            else:
                result['status'] = 'crop_failed'
                self.stats['failed'] += 1
                return result

        # Save cropped plate
        try:
            # Generate filename from URL
            filename = Path(url).stem + '.jpg'
            plate_path = self.output_dir / filename

            cv2.imwrite(str(plate_path), cropped_plate)

            result['status'] = 'success'
            result['plate_path'] = str(plate_path)

        except Exception as e:
            logger.error(f"Error saving plate for {url}: {e}")
            result['status'] = 'save_failed'
            self.stats['failed'] += 1

        return result

    async def process_all_images(self, max_concurrent: int = 20):
        """Process all images with concurrent downloads"""
        records = self.get_all_records()
        self.stats['total'] = len(records)

        logger.info(f"Processing {len(records)} images...")
        print(f"\nProcessing {len(records)} images...")
        print(f"Output directory: {self.output_dir}\n")

        # Create aiohttp session
        connector = aiohttp.TCPConnector(limit=max_concurrent)
        timeout = aiohttp.ClientTimeout(total=60)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Create tasks
            tasks = [
                self.process_single_image(session, record)
                for record in records
            ]

            # Execute with progress bar
            results = []
            for coro in tqdm.as_completed(tasks, total=len(tasks), desc="Extracting plates"):
                result = await coro
                results.append(result)

        return results

    def update_database(self, results: list):
        """Update database with plate extraction results"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Add new columns if they don't exist
        try:
            cursor.execute("""
                ALTER TABLE vehicle_metadata
                ADD COLUMN plate_crop_status TEXT
            """)
        except:
            pass

        try:
            cursor.execute("""
                ALTER TABLE vehicle_metadata
                ADD COLUMN plate_crop_method TEXT
            """)
        except:
            pass

        try:
            cursor.execute("""
                ALTER TABLE vehicle_metadata
                ADD COLUMN plate_path TEXT
            """)
        except:
            pass

        # Update records
        for result in results:
            cursor.execute("""
                UPDATE vehicle_metadata
                SET plate_crop_status = ?,
                    plate_crop_method = ?,
                    plate_path = ?
                WHERE id = ?
            """, (
                result['status'],
                result['method'],
                result['plate_path'],
                result['id']
            ))

        conn.commit()
        conn.close()

        logger.info(f"Updated {len(results)} records in database")

    def save_results_json(self, results: list, output_path: str = "data/phase2_results.json"):
        """Save results to JSON"""
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"Saved results to {output_path}")


async def main():
    """Main execution function for Phase 2"""

    print("\n" + "="*80)
    print("PHASE 2: License Plate Extraction")
    print("="*80 + "\n")

    extractor = PlateExtractor()

    # Process all images
    results = await extractor.process_all_images(max_concurrent=30)

    # Update database
    print("\nUpdating database...")
    extractor.update_database(results)

    # Save results
    extractor.save_results_json(results)

    # Display statistics
    print("\n" + "="*80)
    print("PHASE 2 RESULTS")
    print("="*80)

    stats = extractor.stats
    print(f"\nTotal images: {stats['total']}")
    print(f"Success (bbox): {stats['success_bbox']}")
    print(f"Success (YOLO): {stats['success_yolo']}")
    print(f"Failed: {stats['failed']}")

    success_total = stats['success_bbox'] + stats['success_yolo']
    print(f"\nTotal success: {success_total}/{stats['total']} ({success_total/stats['total']*100:.2f}%)")

    print(f"\n✓ Phase 2 complete!")
    print(f"✓ Cropped plates saved to: {extractor.output_dir}/")
    print(f"✓ Results saved to: data/phase2_results.json")
    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    # Ensure directories exist
    Path("cropped_plates").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

    # Run async main
    asyncio.run(main())
