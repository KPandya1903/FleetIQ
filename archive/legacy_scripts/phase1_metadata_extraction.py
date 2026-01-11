"""
Phase 1: Data Preparation & Metadata Extraction
Reads vehicle_images_input.txt and extracts metadata (upload time, bbox if available)
"""

import asyncio
import aiohttp
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from tqdm.asyncio import tqdm
from typing import Dict, Optional, List, Tuple
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/phase1.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class MetadataExtractor:
    def __init__(self, input_file: str, db_path: str = "data/vehicle_metadata.db"):
        self.input_file = input_file
        self.db_path = db_path
        self.urls: List[str] = []
        self.metadata_cache: Dict = {}

    def init_database(self):
        """Initialize SQLite database with schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Create metadata table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicle_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                upload_time TEXT,
                last_modified TEXT,
                content_type TEXT,
                content_length INTEGER,
                bbox_x REAL,
                bbox_y REAL,
                bbox_w REAL,
                bbox_h REAL,
                metadata_json TEXT,
                extraction_timestamp TEXT,
                status TEXT DEFAULT 'pending'
            )
        ''')

        conn.commit()
        conn.close()
        logger.info(f"Database initialized at {self.db_path}")

    def read_input_file(self) -> List[str]:
        """Read URLs from input file"""
        input_path = Path(self.input_file)

        if not input_path.exists():
            logger.error(f"Input file not found: {self.input_file}")
            raise FileNotFoundError(f"Input file not found: {self.input_file}")

        with open(input_path, 'r') as f:
            urls = [line.strip() for line in f if line.strip()]

        logger.info(f"Read {len(urls)} URLs from {self.input_file}")
        self.urls = urls
        return urls

    async def extract_metadata_from_url(
        self,
        session: aiohttp.ClientSession,
        url: str
    ) -> Dict:
        """
        Extract metadata from a single URL using HEAD request
        """
        metadata = {
            'url': url,
            'upload_time': None,
            'last_modified': None,
            'content_type': None,
            'content_length': None,
            'bbox_x': None,
            'bbox_y': None,
            'bbox_w': None,
            'bbox_h': None,
            'metadata_json': None,
            'status': 'success'
        }

        try:
            # Perform HEAD request to get headers
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                headers = response.headers

                # Extract Last-Modified
                if 'Last-Modified' in headers:
                    metadata['last_modified'] = headers['Last-Modified']

                # Extract content type and length
                metadata['content_type'] = headers.get('Content-Type', 'unknown')

                content_length = headers.get('Content-Length')
                if content_length:
                    metadata['content_length'] = int(content_length)

                # Check for custom headers that might contain upload time
                if 'x-goog-meta-upload-time' in headers:
                    metadata['upload_time'] = headers['x-goog-meta-upload-time']

                # Check for bbox in custom headers
                if 'x-goog-meta-bbox' in headers:
                    try:
                        bbox_str = headers['x-goog-meta-bbox']
                        bbox_parts = bbox_str.split(',')
                        if len(bbox_parts) == 4:
                            metadata['bbox_x'] = float(bbox_parts[0])
                            metadata['bbox_y'] = float(bbox_parts[1])
                            metadata['bbox_w'] = float(bbox_parts[2])
                            metadata['bbox_h'] = float(bbox_parts[3])
                    except Exception as e:
                        logger.warning(f"Failed to parse bbox from headers: {e}")

                # Store all headers as JSON for future reference
                metadata['metadata_json'] = json.dumps(dict(headers))

        except asyncio.TimeoutError:
            logger.warning(f"Timeout extracting metadata from {url}")
            metadata['status'] = 'timeout'
        except Exception as e:
            logger.error(f"Error extracting metadata from {url}: {e}")
            metadata['status'] = 'error'

        return metadata

    async def extract_all_metadata(self, max_concurrent: int = 20):
        """
        Extract metadata from all URLs concurrently
        """
        if not self.urls:
            self.read_input_file()

        logger.info(f"Starting metadata extraction for {len(self.urls)} URLs")

        # Create aiohttp session with connection pooling
        connector = aiohttp.TCPConnector(limit=max_concurrent)
        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Create tasks for all URLs
            tasks = [
                self.extract_metadata_from_url(session, url)
                for url in self.urls
            ]

            # Execute with progress bar
            results = []
            for coro in tqdm.as_completed(tasks, total=len(tasks), desc="Extracting metadata"):
                result = await coro
                results.append(result)

        self.metadata_cache = {r['url']: r for r in results}
        logger.info(f"Metadata extraction complete. Success: {sum(1 for r in results if r['status'] == 'success')}/{len(results)}")

        return results

    def save_to_database(self, metadata_list: List[Dict]):
        """
        Save extracted metadata to SQLite database
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        extraction_timestamp = datetime.now().isoformat()

        for metadata in metadata_list:
            cursor.execute('''
                INSERT OR REPLACE INTO vehicle_metadata
                (url, upload_time, last_modified, content_type, content_length,
                 bbox_x, bbox_y, bbox_w, bbox_h, metadata_json,
                 extraction_timestamp, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                metadata['url'],
                metadata['upload_time'],
                metadata['last_modified'],
                metadata['content_type'],
                metadata['content_length'],
                metadata['bbox_x'],
                metadata['bbox_y'],
                metadata['bbox_w'],
                metadata['bbox_h'],
                metadata['metadata_json'],
                extraction_timestamp,
                metadata['status']
            ))

        conn.commit()
        conn.close()
        logger.info(f"Saved {len(metadata_list)} records to database")

    def get_statistics(self) -> Dict:
        """Get statistics about extracted metadata"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        stats = {}

        # Total URLs
        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata")
        stats['total_urls'] = cursor.fetchone()[0]

        # URLs with last_modified
        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE last_modified IS NOT NULL")
        stats['with_last_modified'] = cursor.fetchone()[0]

        # URLs with bbox
        cursor.execute("SELECT COUNT(*) FROM vehicle_metadata WHERE bbox_x IS NOT NULL")
        stats['with_bbox'] = cursor.fetchone()[0]

        # URLs by status
        cursor.execute("SELECT status, COUNT(*) FROM vehicle_metadata GROUP BY status")
        stats['by_status'] = dict(cursor.fetchall())

        conn.close()
        return stats

    def export_to_json(self, output_path: str = "data/metadata_export.json"):
        """Export metadata to JSON file for inspection"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM vehicle_metadata")
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()

        data = [dict(zip(columns, row)) for row in rows]

        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)

        conn.close()
        logger.info(f"Exported metadata to {output_path}")


async def main():
    """Main execution function for Phase 1"""

    # Initialize extractor
    extractor = MetadataExtractor(input_file="vehicle_images_input.txt")

    # Step 1: Initialize database
    print("\n" + "="*60)
    print("PHASE 1: Data Preparation & Metadata Extraction")
    print("="*60 + "\n")

    extractor.init_database()

    # Step 2: Read input file
    try:
        urls = extractor.read_input_file()
        print(f"✓ Loaded {len(urls)} URLs from input file\n")
    except FileNotFoundError as e:
        print(f"✗ Error: {e}")
        print("Please ensure 'vehicle_images_input.txt' exists in the project root.")
        return

    # Step 3: Extract metadata
    print("Extracting metadata from URLs...")
    metadata_list = await extractor.extract_all_metadata(max_concurrent=30)

    # Step 4: Save to database
    print("\nSaving metadata to database...")
    extractor.save_to_database(metadata_list)

    # Step 5: Export to JSON for inspection
    extractor.export_to_json()

    # Step 6: Display statistics
    print("\n" + "="*60)
    print("PHASE 1 RESULTS")
    print("="*60)
    stats = extractor.get_statistics()

    print(f"\nTotal URLs processed: {stats['total_urls']}")
    print(f"URLs with Last-Modified header: {stats['with_last_modified']}")
    print(f"URLs with embedded bbox: {stats['with_bbox']}")
    print(f"\nStatus breakdown:")
    for status, count in stats['by_status'].items():
        print(f"  {status}: {count}")

    print(f"\n✓ Phase 1 complete!")
    print(f"✓ Database: data/vehicle_metadata.db")
    print(f"✓ JSON export: data/metadata_export.json")
    print("\n" + "="*60 + "\n")


if __name__ == "__main__":
    # Ensure directories exist
    Path("data").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)

    # Run async main
    asyncio.run(main())
