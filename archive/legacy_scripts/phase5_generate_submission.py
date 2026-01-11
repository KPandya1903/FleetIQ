"""
Phase 5: Generate Submission File
- Creates submission.txt with matched URL pairs
- One pair per line, space-separated
- Validates format and completeness
"""

import sqlite3
from pathlib import Path
import logging
from typing import List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/phase5.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class SubmissionGenerator:
    def __init__(self, db_path: str = "data/vehicle_metadata.db",
                 output_path: str = "submission.txt"):
        self.db_path = db_path
        self.output_path = output_path
        self.pairs = []

    def load_matched_pairs(self):
        """Load all matched pairs from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get all matched vehicles with their match IDs
        cursor.execute("""
            SELECT id, url, match_vehicle_id
            FROM vehicle_metadata
            WHERE matched = 1
            ORDER BY id
        """)

        rows = cursor.fetchall()

        # Create pairs (avoid duplicates by only including when id < match_id)
        pairs_set = set()
        for vehicle_id, url, match_id in rows:
            if match_id is not None:
                # Create pair with sorted IDs to avoid duplicates
                pair_ids = tuple(sorted([vehicle_id, match_id]))
                if pair_ids not in pairs_set:
                    pairs_set.add(pair_ids)

                    # Get both URLs
                    cursor.execute("SELECT url FROM vehicle_metadata WHERE id = ?", (vehicle_id,))
                    url1 = cursor.fetchone()[0]

                    cursor.execute("SELECT url FROM vehicle_metadata WHERE id = ?", (match_id,))
                    url2 = cursor.fetchone()[0]

                    self.pairs.append((url1, url2))

        conn.close()

        logger.info(f"Loaded {len(self.pairs)} matched pairs")
        return len(self.pairs)

    def generate_submission_file(self):
        """Generate submission.txt file"""
        with open(self.output_path, 'w') as f:
            for url1, url2 in self.pairs:
                # Write comma-separated URL pair
                f.write(f"{url1},{url2}\n")

        logger.info(f"Generated submission file: {self.output_path}")

    def validate_submission(self) -> dict:
        """Validate the submission file"""
        validation = {
            'total_pairs': 0,
            'valid_format': True,
            'errors': []
        }

        try:
            with open(self.output_path, 'r') as f:
                lines = f.readlines()

            validation['total_pairs'] = len(lines)

            # Check each line
            for i, line in enumerate(lines, 1):
                line = line.strip()
                if not line:
                    validation['errors'].append(f"Line {i}: Empty line")
                    continue

                parts = line.split(',')
                if len(parts) != 2:
                    validation['errors'].append(f"Line {i}: Expected 2 URLs (comma-separated), got {len(parts)}")
                    validation['valid_format'] = False
                    continue

                url1, url2 = parts

                # Check URLs are valid
                if not url1.startswith('http'):
                    validation['errors'].append(f"Line {i}: Invalid URL1: {url1}")
                    validation['valid_format'] = False

                if not url2.startswith('http'):
                    validation['errors'].append(f"Line {i}: Invalid URL2: {url2}")
                    validation['valid_format'] = False

                # Check URLs are different
                if url1 == url2:
                    validation['errors'].append(f"Line {i}: Same URL repeated")
                    validation['valid_format'] = False

        except Exception as e:
            validation['valid_format'] = False
            validation['errors'].append(f"Error reading file: {e}")

        return validation

    def get_statistics(self) -> dict:
        """Get submission statistics"""
        stats = {
            'total_pairs': len(self.pairs),
            'submission_file': self.output_path,
            'file_size_bytes': 0
        }

        # Get file size
        try:
            stats['file_size_bytes'] = Path(self.output_path).stat().st_size
        except:
            pass

        # Get database stats
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata")
        stats['total_vehicles'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE matched = 1")
        stats['matched_vehicles'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE ocr_status_fastalpr = 'success'")
        stats['successful_ocr'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE ocr_status_fastalpr != 'success' OR ocr_status_fastalpr IS NULL")
        stats['failed_ocr'] = cursor.fetchone()[0]

        conn.close()

        return stats


def main():
    """Main execution function for Phase 5"""

    print("\n" + "="*80)
    print("PHASE 5: Generate Submission File")
    print("="*80 + "\n")

    generator = SubmissionGenerator()

    # Load matched pairs
    print("Loading matched pairs from database...")
    pair_count = generator.load_matched_pairs()
    print(f"Found {pair_count} matched pairs")

    # Generate submission file
    print("\nGenerating submission.txt...")
    generator.generate_submission_file()

    # Validate submission
    print("Validating submission file...")
    validation = generator.validate_submission()

    # Get statistics
    stats = generator.get_statistics()

    # Display results
    print("\n" + "="*80)
    print("PHASE 5 RESULTS")
    print("="*80)

    print(f"\nSubmission file: {stats['submission_file']}")
    print(f"Total pairs in submission: {stats['total_pairs']}")
    print(f"File size: {stats['file_size_bytes']:,} bytes")

    print(f"\nDatabase statistics:")
    print(f"  Total vehicles: {stats['total_vehicles']}")
    print(f"  Successful OCR: {stats['successful_ocr']}")
    print(f"  Failed OCR: {stats['failed_ocr']}")
    print(f"  Matched vehicles: {stats['matched_vehicles']} ({stats['matched_vehicles']/stats['total_vehicles']*100:.2f}%)")

    print(f"\nValidation:")
    if validation['valid_format']:
        print(f"  ✓ Format is valid")
        print(f"  ✓ All {validation['total_pairs']} pairs are properly formatted")
    else:
        print(f"  ✗ Validation errors found:")
        for error in validation['errors'][:10]:  # Show first 10 errors
            print(f"    - {error}")

    # Show sample pairs
    print(f"\nSample pairs (first 5):")
    with open(stats['submission_file'], 'r') as f:
        for i, line in enumerate(f, 1):
            if i > 5:
                break
            url1, url2 = line.strip().split(',')
            print(f"  {i}. {url1},{url2}")

    print(f"\n✓ Phase 5 complete!")
    print(f"✓ Submission file generated: {stats['submission_file']}")
    print(f"✓ Ready for submission with {stats['total_pairs']} matched pairs")
    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    main()
