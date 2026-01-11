"""
Main entry point for the Vehicle Re-Identification System.
"""

import asyncio
import argparse
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config_loader import ConfigLoader
from src.utils.logger import setup_logger
from src.data.metadata_extractor import MetadataExtractor
from src.ocr.alpr_engine import ALPREngine
from src.matching.vehicle_matcher import VehicleMatcher


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Automated Vehicle Re-Identification & Temporal Matching System"
    )

    parser.add_argument(
        '--config',
        type=str,
        default='configs/config.yaml',
        help='Path to configuration file'
    )

    parser.add_argument(
        '--input',
        type=str,
        default='vehicle_images_input.txt',
        help='Path to input file with vehicle image URLs'
    )

    parser.add_argument(
        '--phase',
        type=str,
        choices=['all', 'metadata', 'ocr', 'matching', 'export'],
        default='all',
        help='Phase to execute'
    )

    parser.add_argument(
        '--output',
        type=str,
        default='submission.txt',
        help='Path to output submission file'
    )

    return parser.parse_args()


async def phase_metadata_extraction(config: ConfigLoader, input_file: str):
    """Execute metadata extraction phase."""
    logger = setup_logger(
        "metadata_extraction",
        log_file=config.get('logging.file'),
        level=config.get('logging.level', 'INFO')
    )

    logger.info("="*80)
    logger.info("PHASE 1: Metadata Extraction")
    logger.info("="*80)

    extractor = MetadataExtractor(
        db_path=config.get('database.path'),
        max_concurrent=config.get('image_processing.max_concurrent_downloads', 30)
    )

    # Create database
    extractor.create_database()

    # Load URLs
    urls = extractor.load_urls_from_file(input_file)

    # Extract metadata
    metadata_list = await extractor.batch_extract(urls)

    # Save to database
    saved_count = extractor.save_to_database(metadata_list)

    logger.info(f"✓ Phase 1 complete: {saved_count} records saved")
    logger.info("="*80)


def phase_ocr_extraction(config: ConfigLoader):
    """Execute OCR extraction phase."""
    logger = setup_logger(
        "ocr_extraction",
        log_file=config.get('logging.file'),
        level=config.get('logging.level', 'INFO')
    )

    logger.info("="*80)
    logger.info("PHASE 2: License Plate OCR")
    logger.info("="*80)

    # Initialize ALPR engine
    alpr = ALPREngine(
        fast_alpr_enabled=config.get('ocr.fast_alpr.enabled', True),
        easyocr_enabled=config.get('ocr.easyocr.enabled', True),
        confidence_threshold=config.get('ocr.fast_alpr.confidence_threshold', 0.5)
    )

    # Process cropped plates
    cropped_dir = Path("cropped_plates")
    if not cropped_dir.exists():
        logger.error(f"Cropped plates directory not found: {cropped_dir}")
        return

    # Get all cropped plate images
    image_files = list(cropped_dir.glob("*.jpg")) + list(cropped_dir.glob("*.jpeg"))

    logger.info(f"Processing {len(image_files)} plate images...")

    # TODO: Implement batch processing with database updates
    # This would involve:
    # 1. Load each cropped plate
    # 2. Run ALPR
    # 3. Update database with OCR results

    logger.info("✓ Phase 2 complete")
    logger.info("="*80)


def phase_matching(config: ConfigLoader):
    """Execute vehicle matching phase."""
    logger = setup_logger(
        "matching",
        log_file=config.get('logging.file'),
        level=config.get('logging.level', 'INFO')
    )

    logger.info("="*80)
    logger.info("PHASE 3: Vehicle Matching")
    logger.info("="*80)

    matcher = VehicleMatcher(
        db_path=config.get('database.path'),
        min_similarity=config.get('matching.min_similarity_threshold', 75),
        max_time_diff_hours=config.get('matching.max_time_difference_hours', 72)
    )

    # Load vehicles
    matcher.load_vehicles()

    # Perform matching
    num_matches = matcher.match_greedy()

    # Save matches
    matcher.save_matches()

    # Update database
    matcher.update_database()

    # Display statistics
    stats = matcher.get_statistics()

    logger.info(f"Total vehicles: {stats['total_vehicles']}")
    logger.info(f"Matched pairs: {stats['matched_pairs']}")
    logger.info(f"Match rate: {stats['matched_pairs']*2/stats['total_vehicles']*100:.2f}%")

    if stats['matched_pairs'] > 0:
        logger.info(f"Average similarity: {stats['avg_similarity']:.2f}%")

    logger.info("✓ Phase 3 complete")
    logger.info("="*80)


def phase_export_submission(config: ConfigLoader, output_file: str):
    """Export matched pairs to submission file."""
    logger = setup_logger(
        "export",
        log_file=config.get('logging.file'),
        level=config.get('logging.level', 'INFO')
    )

    logger.info("="*80)
    logger.info("PHASE 4: Export Submission")
    logger.info("="*80)

    import sqlite3

    conn = sqlite3.connect(config.get('database.path'))
    cursor = conn.cursor()

    # Get all matched pairs
    cursor.execute("""
        SELECT id, url, match_vehicle_id
        FROM vehicle_metadata
        WHERE matched = 1
        ORDER BY id
    """)

    rows = cursor.fetchall()

    # Create pairs (avoid duplicates)
    pairs_set = set()
    pairs = []

    for vehicle_id, url, match_id in rows:
        if match_id is not None:
            pair_ids = tuple(sorted([vehicle_id, match_id]))
            if pair_ids not in pairs_set:
                pairs_set.add(pair_ids)

                # Get both URLs
                cursor.execute("SELECT url FROM vehicle_metadata WHERE id = ?", (vehicle_id,))
                url1 = cursor.fetchone()[0]

                cursor.execute("SELECT url FROM vehicle_metadata WHERE id = ?", (match_id,))
                url2 = cursor.fetchone()[0]

                pairs.append((url1, url2))

    conn.close()

    # Write to submission file
    with open(output_file, 'w') as f:
        for url1, url2 in pairs:
            f.write(f"{url1},{url2}\n")

    logger.info(f"✓ Exported {len(pairs)} matched pairs to {output_file}")
    logger.info("="*80)


async def main():
    """Main execution function."""
    args = parse_arguments()

    # Load configuration
    config = ConfigLoader(args.config)

    # Create necessary directories
    Path("logs").mkdir(exist_ok=True)
    Path("results").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)

    # Execute requested phase(s)
    if args.phase in ['all', 'metadata']:
        await phase_metadata_extraction(config, args.input)

    if args.phase in ['all', 'ocr']:
        phase_ocr_extraction(config)

    if args.phase in ['all', 'matching']:
        phase_matching(config)

    if args.phase in ['all', 'export']:
        phase_export_submission(config, args.output)

    print("\n✓ Pipeline execution complete!")


if __name__ == "__main__":
    asyncio.run(main())
