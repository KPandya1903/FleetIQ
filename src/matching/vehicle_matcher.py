"""
Vehicle matching module using fuzzy string matching and temporal logic.
"""

import sqlite3
from datetime import datetime
from typing import List, Dict, Tuple, Optional
from fuzzywuzzy import fuzz
from tqdm import tqdm
import logging

logger = logging.getLogger(__name__)


class VehicleMatcher:
    """
    Matches entry/exit vehicle images using license plate similarity and timestamps.
    """

    def __init__(
        self,
        db_path: str = "data/vehicle_metadata.db",
        min_similarity: int = 75,
        max_time_diff_hours: float = 72
    ):
        """
        Initialize vehicle matcher.

        Args:
            db_path: Path to SQLite database
            min_similarity: Minimum plate similarity threshold (0-100)
            max_time_diff_hours: Maximum time difference between entry/exit
        """
        self.db_path = db_path
        self.min_similarity = min_similarity
        self.max_time_diff_hours = max_time_diff_hours

        self.vehicles: List[Dict] = []
        self.matches: List[Dict] = []

    def load_vehicles(self) -> int:
        """
        Load vehicles with successful OCR from database.

        Returns:
            Number of vehicles loaded
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, url, last_modified, plate_text,
                       ocr_confidence, ocr_method
                FROM vehicle_metadata
                WHERE ocr_status = 'success'
                ORDER BY id
            """)

            rows = cursor.fetchall()

            self.vehicles = []
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

            logger.info(f"Loaded {len(self.vehicles)} vehicles with successful OCR")
            return len(self.vehicles)

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            raise

    def calculate_similarity(self, plate1: str, plate2: str) -> int:
        """
        Calculate similarity between two plate texts using fuzzy matching.

        Args:
            plate1: First plate text
            plate2: Second plate text

        Returns:
            Similarity score (0-100)
        """
        if not plate1 or not plate2:
            return 0

        # Use token_sort_ratio for better handling of character order variations
        return fuzz.token_sort_ratio(plate1, plate2)

    def parse_timestamp(self, timestamp_str: str) -> Optional[datetime]:
        """
        Parse timestamp string to datetime object.

        Args:
            timestamp_str: Timestamp string from metadata

        Returns:
            datetime object or None
        """
        if not timestamp_str:
            return None

        formats = [
            '%a, %d %b %Y %H:%M:%S %Z',  # HTTP date format
            '%Y-%m-%dT%H:%M:%SZ',         # ISO format
            '%Y-%m-%d %H:%M:%S'           # Simple format
        ]

        for fmt in formats:
            try:
                return datetime.strptime(timestamp_str, fmt)
            except ValueError:
                continue

        logger.warning(f"Could not parse timestamp: {timestamp_str}")
        return None

    def calculate_time_diff_hours(
        self,
        time1_str: str,
        time2_str: str
    ) -> Optional[float]:
        """
        Calculate time difference in hours between two timestamps.

        Args:
            time1_str: First timestamp string
            time2_str: Second timestamp string

        Returns:
            Time difference in hours or None
        """
        dt1 = self.parse_timestamp(time1_str)
        dt2 = self.parse_timestamp(time2_str)

        if not dt1 or not dt2:
            return None

        diff_seconds = abs((dt2 - dt1).total_seconds())
        return diff_seconds / 3600.0

    def find_best_match(
        self,
        vehicle: Dict,
        candidates: List[Dict]
    ) -> Optional[Tuple[Dict, float]]:
        """
        Find the best matching candidate for a vehicle.

        Args:
            vehicle: Vehicle to match
            candidates: List of candidate vehicles

        Returns:
            Tuple of (best_candidate, match_score) or None
        """
        best_candidate = None
        best_score = 0.0

        for candidate in candidates:
            # Skip if already matched or same vehicle
            if candidate['matched'] or candidate['id'] == vehicle['id']:
                continue

            # Calculate plate similarity
            similarity = self.calculate_similarity(
                vehicle['plate_text'],
                candidate['plate_text']
            )

            # Skip if below threshold
            if similarity < self.min_similarity:
                continue

            # Calculate time difference
            time_diff = self.calculate_time_diff_hours(
                vehicle['upload_time'],
                candidate['upload_time']
            )

            # Apply temporal filter
            if time_diff is not None and time_diff > self.max_time_diff_hours:
                # Only accept if very high similarity
                if similarity < 95:
                    continue

            # Combined score: similarity + time proximity bonus
            score = float(similarity)

            if time_diff is not None:
                # Time bonus: closer in time = higher score (max +10)
                time_bonus = max(0, 10 - (time_diff / self.max_time_diff_hours * 10))
                score += time_bonus

            # Update best candidate
            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate:
            return (best_candidate, best_score)

        return None

    def match_greedy(self) -> int:
        """
        Perform greedy matching algorithm.

        Returns:
            Number of matches found
        """
        logger.info("Starting greedy matching algorithm...")

        # Phase 1: Exact matches (100% similarity)
        exact_matches = 0
        plate_groups = {}

        # Group vehicles by exact plate text
        for vehicle in self.vehicles:
            plate = vehicle['plate_text']
            if plate not in plate_groups:
                plate_groups[plate] = []
            plate_groups[plate].append(vehicle)

        # Match exact duplicates
        for plate, group in plate_groups.items():
            if len(group) >= 2:
                # Sort by confidence
                group_sorted = sorted(group, key=lambda x: x['confidence'], reverse=True)

                # Pair them up
                i = 0
                while i < len(group_sorted) - 1:
                    v1 = group_sorted[i]
                    v2 = group_sorted[i + 1]

                    if not v1['matched'] and not v2['matched']:
                        v1['matched'] = True
                        v2['matched'] = True
                        v1['match_id'] = v2['id']
                        v2['match_id'] = v1['id']

                        self.matches.append({
                            'vehicle1_id': v1['id'],
                            'vehicle1_url': v1['url'],
                            'vehicle1_plate': v1['plate_text'],
                            'vehicle2_id': v2['id'],
                            'vehicle2_url': v2['url'],
                            'vehicle2_plate': v2['plate_text'],
                            'similarity': 100,
                            'time_diff_hours': self.calculate_time_diff_hours(
                                v1['upload_time'], v2['upload_time']
                            )
                        })

                        exact_matches += 1
                        i += 2
                    else:
                        i += 1

        logger.info(f"Phase 1: Found {exact_matches} exact matches")

        # Phase 2: Fuzzy matches
        unmatched = [v for v in self.vehicles if not v['matched']]
        sorted_vehicles = sorted(unmatched, key=lambda x: x['confidence'], reverse=True)

        fuzzy_matches = 0
        for vehicle in tqdm(sorted_vehicles, desc="Finding fuzzy matches"):
            if vehicle['matched']:
                continue

            match_result = self.find_best_match(vehicle, self.vehicles)

            if match_result:
                candidate, score = match_result

                vehicle['matched'] = True
                candidate['matched'] = True
                vehicle['match_id'] = candidate['id']
                candidate['match_id'] = vehicle['id']

                self.matches.append({
                    'vehicle1_id': vehicle['id'],
                    'vehicle1_url': vehicle['url'],
                    'vehicle1_plate': vehicle['plate_text'],
                    'vehicle2_id': candidate['id'],
                    'vehicle2_url': candidate['url'],
                    'vehicle2_plate': candidate['plate_text'],
                    'similarity': self.calculate_similarity(
                        vehicle['plate_text'], candidate['plate_text']
                    ),
                    'time_diff_hours': self.calculate_time_diff_hours(
                        vehicle['upload_time'], candidate['upload_time']
                    )
                })

                fuzzy_matches += 1

        logger.info(f"Phase 2: Found {fuzzy_matches} fuzzy matches")
        logger.info(f"Total matches: {len(self.matches)}")

        return len(self.matches)

    def save_matches(self, output_path: str = "results/matches.json") -> None:
        """
        Save matches to JSON file.

        Args:
            output_path: Path to output JSON file
        """
        import json
        from pathlib import Path

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            json.dump(self.matches, f, indent=2)

        logger.info(f"Saved {len(self.matches)} matches to {output_path}")

    def update_database(self) -> None:
        """Update database with match information."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Add match columns if they don't exist
            try:
                cursor.execute("ALTER TABLE vehicle_metadata ADD COLUMN matched INTEGER DEFAULT 0")
                cursor.execute("ALTER TABLE vehicle_metadata ADD COLUMN match_vehicle_id INTEGER")
            except sqlite3.OperationalError:
                pass  # Columns already exist

            # Update matched vehicles
            for vehicle in self.vehicles:
                cursor.execute("""
                    UPDATE vehicle_metadata
                    SET matched = ?, match_vehicle_id = ?
                    WHERE id = ?
                """, (
                    1 if vehicle['matched'] else 0,
                    vehicle['match_id'],
                    vehicle['id']
                ))

            conn.commit()
            conn.close()

            logger.info("Database updated with match information")

        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            raise

    def get_statistics(self) -> Dict:
        """
        Get matching statistics.

        Returns:
            Dictionary with statistics
        """
        stats = {
            'total_vehicles': len(self.vehicles),
            'matched_pairs': len(self.matches),
            'matched_vehicles': len([v for v in self.vehicles if v['matched']]),
            'unmatched_vehicles': len([v for v in self.vehicles if not v['matched']])
        }

        if self.matches:
            similarities = [m['similarity'] for m in self.matches]
            stats['avg_similarity'] = sum(similarities) / len(similarities)
            stats['min_similarity'] = min(similarities)
            stats['max_similarity'] = max(similarities)

            time_diffs = [m['time_diff_hours'] for m in self.matches if m['time_diff_hours'] is not None]
            if time_diffs:
                stats['avg_time_diff_hours'] = sum(time_diffs) / len(time_diffs)
                stats['min_time_diff_hours'] = min(time_diffs)
                stats['max_time_diff_hours'] = max(time_diffs)

        return stats
