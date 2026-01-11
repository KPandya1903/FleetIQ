"""
Phase 1 - Part 2: Extract Bounding Box from Google Cloud Storage Metadata
Parses the x-goog-meta-image_processing_tasks header to extract license plate polygons
"""

import sqlite3
import json
import logging
from typing import Dict, List, Tuple, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/phase1_bbox.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class BboxExtractor:
    def __init__(self, db_path: str = "data/vehicle_metadata.db"):
        self.db_path = db_path

    def polygon_to_bbox(self, polygon: List[Dict[str, int]]) -> Tuple[int, int, int, int]:
        """
        Convert a polygon (list of points) to a bounding box (x, y, width, height)
        """
        if not polygon or len(polygon) < 2:
            return None

        x_coords = [p['x'] for p in polygon]
        y_coords = [p['y'] for p in polygon]

        x_min = min(x_coords)
        y_min = min(y_coords)
        x_max = max(x_coords)
        y_max = max(y_coords)

        width = x_max - x_min
        height = y_max - y_min

        return (x_min, y_min, width, height)

    def extract_bbox_from_metadata(self, metadata_json_str: str) -> Optional[Dict]:
        """
        Extract bounding box from the metadata_json field
        """
        try:
            # Parse the outer JSON (all headers)
            headers = json.loads(metadata_json_str)

            # Check if the image_processing_tasks header exists
            if 'x-goog-meta-image_processing_tasks' not in headers:
                return None

            # Parse the inner JSON (the tasks array)
            tasks_json_str = headers['x-goog-meta-image_processing_tasks']
            tasks = json.loads(tasks_json_str)

            # Look for license_plate task
            for task in tasks:
                if task.get('suffix') == 'license_plate':
                    polygon = task.get('cropping_polygon', [])

                    if polygon:
                        bbox = self.polygon_to_bbox(polygon)

                        if bbox:
                            return {
                                'bbox_x': bbox[0],
                                'bbox_y': bbox[1],
                                'bbox_w': bbox[2],
                                'bbox_h': bbox[3],
                                'polygon': polygon  # Store original polygon too
                            }

            return None

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error extracting bbox: {e}")
            return None

    def update_all_bboxes(self):
        """
        Update all records in the database with extracted bounding boxes
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get all records with metadata
        cursor.execute("SELECT id, url, metadata_json FROM vehicle_metadata WHERE metadata_json IS NOT NULL")
        records = cursor.fetchall()

        logger.info(f"Processing {len(records)} records for bbox extraction")

        successful_extractions = 0
        failed_extractions = 0

        for record_id, url, metadata_json in records:
            bbox_data = self.extract_bbox_from_metadata(metadata_json)

            if bbox_data:
                # Update the record with bbox information
                cursor.execute('''
                    UPDATE vehicle_metadata
                    SET bbox_x = ?, bbox_y = ?, bbox_w = ?, bbox_h = ?
                    WHERE id = ?
                ''', (
                    bbox_data['bbox_x'],
                    bbox_data['bbox_y'],
                    bbox_data['bbox_w'],
                    bbox_data['bbox_h'],
                    record_id
                ))
                successful_extractions += 1
            else:
                failed_extractions += 1

        conn.commit()
        conn.close()

        logger.info(f"Bbox extraction complete: {successful_extractions} successful, {failed_extractions} failed")

        return successful_extractions, failed_extractions

    def get_bbox_statistics(self) -> Dict:
        """
        Get statistics about extracted bounding boxes
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}

        # Total records
        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata")
        stats['total_records'] = cursor.fetchone()[0]

        # Records with bbox
        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE bbox_x IS NOT NULL")
        stats['with_bbox'] = cursor.fetchone()[0]

        # Bbox dimensions statistics
        cursor.execute("SELECT MIN(bbox_w), MAX(bbox_w), AVG(bbox_w) FROM vehicle_metadata WHERE bbox_w IS NOT NULL")
        min_w, max_w, avg_w = cursor.fetchone()

        cursor.execute("SELECT MIN(bbox_h), MAX(bbox_h), AVG(bbox_h) FROM vehicle_metadata WHERE bbox_h IS NOT NULL")
        min_h, max_h, avg_h = cursor.fetchone()

        stats['width'] = {'min': min_w, 'max': max_w, 'avg': avg_w}
        stats['height'] = {'min': min_h, 'max': max_h, 'avg': avg_h}

        # Sample bboxes
        cursor.execute("SELECT url, bbox_x, bbox_y, bbox_w, bbox_h FROM vehicle_metadata WHERE bbox_x IS NOT NULL LIMIT 5")
        stats['samples'] = cursor.fetchall()

        conn.close()

        return stats

    def export_bbox_data(self, output_path: str = "data/bbox_export.json"):
        """
        Export all records with bbox data to JSON
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, url, bbox_x, bbox_y, bbox_w, bbox_h, last_modified
            FROM vehicle_metadata
            WHERE bbox_x IS NOT NULL
        """)

        columns = ['id', 'url', 'bbox_x', 'bbox_y', 'bbox_w', 'bbox_h', 'last_modified']
        rows = cursor.fetchall()

        data = [dict(zip(columns, row)) for row in rows]

        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)

        conn.close()
        logger.info(f"Exported {len(data)} records with bbox to {output_path}")

        return len(data)


def main():
    """Main execution function"""

    print("\n" + "="*70)
    print("PHASE 1 - PART 2: Bounding Box Extraction")
    print("="*70 + "\n")

    extractor = BboxExtractor()

    # Extract and update all bboxes
    print("Extracting bounding boxes from metadata...")
    successful, failed = extractor.update_all_bboxes()

    print(f"\n✓ Extraction complete:")
    print(f"  Successful: {successful}")
    print(f"  Failed: {failed}")

    # Get statistics
    print("\n" + "="*70)
    print("BOUNDING BOX STATISTICS")
    print("="*70)

    stats = extractor.get_bbox_statistics()

    print(f"\nTotal records: {stats['total_records']}")
    print(f"Records with bbox: {stats['with_bbox']} ({stats['with_bbox']/stats['total_records']*100:.1f}%)")

    print(f"\nBbox dimensions:")
    print(f"  Width:  min={stats['width']['min']}, max={stats['width']['max']}, avg={stats['width']['avg']:.1f}")
    print(f"  Height: min={stats['height']['min']}, max={stats['height']['max']}, avg={stats['height']['avg']:.1f}")

    print(f"\nSample bboxes (first 5):")
    for i, (url, x, y, w, h) in enumerate(stats['samples'], 1):
        print(f"  {i}. {url[-50:]}")
        print(f"     Bbox: x={x}, y={y}, w={w}, h={h}")

    # Export to JSON
    print("\nExporting bbox data to JSON...")
    count = extractor.export_bbox_data()
    print(f"✓ Exported {count} records to data/bbox_export.json")

    print("\n" + "="*70)
    print("✓ Phase 1 - Part 2 COMPLETE!")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
