"""
Phase 4: Matching Algorithm
- Fuzzy matching using Levenshtein distance for plate similarity
- Time-interval logic using upload_time metadata
- Global optimization for pairing vehicles
- Handles cases where OCR failed for some plates
"""

import sqlite3
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import logging
from datetime import datetime
from fuzzywuzzy import fuzz
import json
from tqdm import tqdm

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/phase4.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class VehicleMatcher:
    def __init__(self, db_path: str = "data/vehicle_metadata.db"):
        self.db_path = db_path
        self.vehicles = []
        self.matches = []

        # Matching parameters
        self.MIN_SIMILARITY_THRESHOLD = 75  # Minimum fuzzy match score (0-100)
        self.MAX_TIME_DIFF_HOURS = 72  # Maximum time difference in hours

        # Stats
        self.stats = {
            'total_vehicles': 0,
            'vehicles_with_plates': 0,
            'matched_pairs': 0,
            'unmatched': 0
        }

    def load_vehicles(self):
        """Load all vehicles with successful OCR from database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Get all vehicles with successful OCR
        cursor.execute("""
            SELECT id, url, last_modified, plate_text_fastalpr,
                   ocr_confidence_fastalpr, ocr_method
            FROM vehicle_metadata
            WHERE ocr_status_fastalpr = 'success'
            ORDER BY id
        """)

        rows = cursor.fetchall()

        for row in rows:
            vehicle = {
                'id': row[0],
                'url': row[1],
                'upload_time': row[2],
                'plate_text': row[3],
                'confidence': row[4],
                'method': row[5],
                'matched': False,
                'match_id': None
            }
            self.vehicles.append(vehicle)

        conn.close()

        self.stats['total_vehicles'] = len(self.vehicles)
        self.stats['vehicles_with_plates'] = len(self.vehicles)

        logger.info(f"Loaded {len(self.vehicles)} vehicles with successful OCR")

    def parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """Parse upload_time string to datetime object"""
        if not timestamp_str:
            return None

        try:
            # Try different formats
            formats = [
                '%a, %d %b %Y %H:%M:%S %Z',  # "Wed, 21 Oct 2015 07:28:00 GMT"
                '%Y-%m-%dT%H:%M:%SZ',         # ISO format
                '%Y-%m-%d %H:%M:%S'           # Simple format
            ]

            for fmt in formats:
                try:
                    return datetime.strptime(timestamp_str, fmt)
                except ValueError:
                    continue

            # If none worked, try stripping timezone and parsing
            timestamp_str = timestamp_str.replace(' GMT', '').replace(' UTC', '')
            return datetime.strptime(timestamp_str, '%a, %d %b %Y %H:%M:%S')

        except Exception as e:
            logger.warning(f"Failed to parse timestamp: {timestamp_str} - {e}")
            return None

    def calculate_similarity(self, plate1: str, plate2: str) -> int:
        """
        Calculate similarity between two plate texts
        Returns score 0-100 (100 = exact match)
        """
        if not plate1 or not plate2:
            return 0

        # Use token_sort_ratio which handles character order variations better
        return fuzz.token_sort_ratio(plate1, plate2)

    def calculate_time_diff_hours(self, time1_str: str, time2_str: str) -> Optional[float]:
        """Calculate time difference in hours between two timestamps"""
        dt1 = self.parse_timestamp(time1_str)
        dt2 = self.parse_timestamp(time2_str)

        if not dt1 or not dt2:
            return None

        diff = abs((dt2 - dt1).total_seconds()) / 3600.0
        return diff

    def find_best_match(self, vehicle: Dict, candidates: List[Dict]) -> Optional[Tuple[Dict, float]]:
        """
        Find the best matching candidate for a vehicle
        Returns (best_candidate, match_score) or None
        """
        best_candidate = None
        best_score = 0.0

        for candidate in candidates:
            # Skip if already matched
            if candidate['matched']:
                continue

            # Skip if same vehicle
            if candidate['id'] == vehicle['id']:
                continue

            # Calculate plate similarity
            similarity = self.calculate_similarity(
                vehicle['plate_text'],
                candidate['plate_text']
            )

            # Skip if below threshold
            if similarity < self.MIN_SIMILARITY_THRESHOLD:
                continue

            # Calculate time difference
            time_diff = self.calculate_time_diff_hours(
                vehicle['upload_time'],
                candidate['upload_time']
            )

            # Skip if time difference too large (or if we couldn't parse times)
            if time_diff is None or time_diff > self.MAX_TIME_DIFF_HOURS:
                # If no valid time, still consider if plate similarity is very high
                if similarity < 95:
                    continue

            # Combined score: prioritize plate similarity, with time bonus
            score = similarity

            # Time bonus: closer in time = higher score
            if time_diff is not None:
                # Normalize time to 0-10 range (closer = higher)
                time_score = max(0, 10 - (time_diff / self.MAX_TIME_DIFF_HOURS * 10))
                score += time_score

            # Update best candidate
            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate:
            return (best_candidate, best_score)

        return None

    def greedy_matching(self):
        """
        Improved greedy matching algorithm:
        1. Sort vehicles by OCR confidence (highest first)
        2. For each vehicle, find best match from remaining candidates
        3. Handle exact matches first, then fuzzy matches
        4. Mark both as matched
        """
        logger.info("Starting improved greedy matching algorithm...")
        print("\nMatching vehicles...")

        # Phase 1: Match exact duplicates first (100% similarity)
        exact_matches_count = 0
        plate_groups = {}

        # Group vehicles by exact plate text
        for vehicle in self.vehicles:
            plate = vehicle['plate_text']
            if plate not in plate_groups:
                plate_groups[plate] = []
            plate_groups[plate].append(vehicle)

        # For each group with 2+ vehicles, match them pairwise
        for plate, group in plate_groups.items():
            if len(group) >= 2:
                # Sort by confidence within group
                group_sorted = sorted(group, key=lambda x: x['confidence'], reverse=True)

                # Match pairs within this group
                i = 0
                while i < len(group_sorted) - 1:
                    v1 = group_sorted[i]
                    v2 = group_sorted[i + 1]

                    if not v1['matched'] and not v2['matched']:
                        # Mark both as matched
                        v1['matched'] = True
                        v2['matched'] = True
                        v1['match_id'] = v2['id']
                        v2['match_id'] = v1['id']

                        # Store match
                        match = {
                            'vehicle1_id': v1['id'],
                            'vehicle1_url': v1['url'],
                            'vehicle1_plate': v1['plate_text'],
                            'vehicle2_id': v2['id'],
                            'vehicle2_url': v2['url'],
                            'vehicle2_plate': v2['plate_text'],
                            'similarity': 100,
                            'time_diff_hours': self.calculate_time_diff_hours(v1['upload_time'], v2['upload_time']),
                            'match_score': 100
                        }
                        self.matches.append(match)
                        exact_matches_count += 1
                        i += 2
                    else:
                        i += 1

        logger.info(f"Phase 1: Found {exact_matches_count} exact matches")

        # Phase 2: Fuzzy matching for remaining unmatched vehicles
        unmatched = [v for v in self.vehicles if not v['matched']]
        sorted_vehicles = sorted(unmatched, key=lambda x: x['confidence'], reverse=True)

        fuzzy_matches_count = 0
        for vehicle in tqdm(sorted_vehicles, desc="Finding fuzzy matches"):
            # Skip if already matched
            if vehicle['matched']:
                continue

            # Find best match
            match_result = self.find_best_match(vehicle, self.vehicles)

            if match_result:
                candidate, score = match_result

                # Mark both as matched
                vehicle['matched'] = True
                candidate['matched'] = True
                vehicle['match_id'] = candidate['id']
                candidate['match_id'] = vehicle['id']

                # Store match
                match = {
                    'vehicle1_id': vehicle['id'],
                    'vehicle1_url': vehicle['url'],
                    'vehicle1_plate': vehicle['plate_text'],
                    'vehicle2_id': candidate['id'],
                    'vehicle2_url': candidate['url'],
                    'vehicle2_plate': candidate['plate_text'],
                    'similarity': self.calculate_similarity(vehicle['plate_text'], candidate['plate_text']),
                    'time_diff_hours': self.calculate_time_diff_hours(vehicle['upload_time'], candidate['upload_time']),
                    'match_score': score
                }

                self.matches.append(match)
                fuzzy_matches_count += 1

        logger.info(f"Phase 2: Found {fuzzy_matches_count} fuzzy matches")

        self.stats['matched_pairs'] = len(self.matches)
        self.stats['unmatched'] = len([v for v in self.vehicles if not v['matched']])

        logger.info(f"Matching complete: {len(self.matches)} total pairs found")

    def save_matches(self, output_path: str = "data/phase4_matches.json"):
        """Save matches to JSON file"""
        with open(output_path, 'w') as f:
            json.dump(self.matches, f, indent=2)

        logger.info(f"Saved {len(self.matches)} matches to {output_path}")

    def update_database(self):
        """Update database with match information"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Add match columns
        try:
            cursor.execute("ALTER TABLE vehicle_metadata ADD COLUMN matched INTEGER DEFAULT 0")
        except:
            pass

        try:
            cursor.execute("ALTER TABLE vehicle_metadata ADD COLUMN match_vehicle_id INTEGER")
        except:
            pass

        # Update matched vehicles
        for vehicle in self.vehicles:
            cursor.execute("""
                UPDATE vehicle_metadata
                SET matched = ?,
                    match_vehicle_id = ?
                WHERE id = ?
            """, (
                1 if vehicle['matched'] else 0,
                vehicle['match_id'],
                vehicle['id']
            ))

        conn.commit()
        conn.close()

        logger.info("Database updated with match information")

    def get_statistics(self) -> Dict:
        """Get matching statistics"""
        stats = self.stats.copy()

        if self.matches:
            similarities = [m['similarity'] for m in self.matches]
            stats['avg_similarity'] = sum(similarities) / len(similarities)
            stats['min_similarity'] = min(similarities)
            stats['max_similarity'] = max(similarities)

            # Time differences (excluding None values)
            time_diffs = [m['time_diff_hours'] for m in self.matches if m['time_diff_hours'] is not None]
            if time_diffs:
                stats['avg_time_diff_hours'] = sum(time_diffs) / len(time_diffs)
                stats['min_time_diff_hours'] = min(time_diffs)
                stats['max_time_diff_hours'] = max(time_diffs)

        return stats


def main():
    """Main execution function for Phase 4"""

    print("\n" + "="*80)
    print("PHASE 4: Vehicle Matching with Fuzzy Logic")
    print("="*80 + "\n")

    matcher = VehicleMatcher()

    # Load vehicles
    print("Loading vehicles from database...")
    matcher.load_vehicles()

    # Perform matching
    matcher.greedy_matching()

    # Save results
    print("\nSaving matches...")
    matcher.save_matches()

    # Update database
    print("Updating database...")
    matcher.update_database()

    # Display statistics
    print("\n" + "="*80)
    print("PHASE 4 RESULTS")
    print("="*80)

    stats = matcher.get_statistics()

    print(f"\nTotal vehicles with plates: {stats['vehicles_with_plates']}")
    print(f"Matched pairs: {stats['matched_pairs']}")
    print(f"Unmatched vehicles: {stats['unmatched']}")
    print(f"Match rate: {stats['matched_pairs']*2/stats['vehicles_with_plates']*100:.2f}%")

    if stats['matched_pairs'] > 0:
        print(f"\nSimilarity scores:")
        print(f"  Average: {stats['avg_similarity']:.2f}%")
        print(f"  Min: {stats['min_similarity']:.2f}%")
        print(f"  Max: {stats['max_similarity']:.2f}%")

        if 'avg_time_diff_hours' in stats:
            print(f"\nTime differences:")
            print(f"  Average: {stats['avg_time_diff_hours']:.2f} hours")
            print(f"  Min: {stats['min_time_diff_hours']:.2f} hours")
            print(f"  Max: {stats['max_time_diff_hours']:.2f} hours")

    # Show sample matches
    print(f"\nSample matches (top 5 by similarity):")
    top_matches = sorted(matcher.matches, key=lambda x: x['similarity'], reverse=True)[:5]
    for i, match in enumerate(top_matches, 1):
        print(f"\n  {i}. Similarity: {match['similarity']:.1f}%")
        print(f"     Plate 1: {match['vehicle1_plate']}")
        print(f"     Plate 2: {match['vehicle2_plate']}")
        if match['time_diff_hours']:
            print(f"     Time diff: {match['time_diff_hours']:.2f} hours")

    print(f"\n✓ Phase 4 complete!")
    print(f"✓ Matches saved to: data/phase4_matches.json")
    print(f"✓ Database updated with match information")
    print("\n" + "="*80 + "\n")


if __name__ == "__main__":
    Path("logs").mkdir(exist_ok=True)
    main()
