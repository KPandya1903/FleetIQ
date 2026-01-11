"""
Unit tests for vehicle matching logic.
"""

import unittest
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.matching.vehicle_matcher import VehicleMatcher


class TestVehicleMatcher(unittest.TestCase):
    """Test cases for VehicleMatcher class."""

    def setUp(self):
        """Set up test fixtures."""
        self.matcher = VehicleMatcher()

    def test_calculate_similarity_exact(self):
        """Test exact match similarity."""
        similarity = self.matcher.calculate_similarity("ABC123", "ABC123")
        self.assertEqual(similarity, 100)

    def test_calculate_similarity_different(self):
        """Test completely different plates."""
        similarity = self.matcher.calculate_similarity("ABC123", "XYZ789")
        self.assertLess(similarity, 50)

    def test_calculate_similarity_similar(self):
        """Test similar but not identical plates."""
        similarity = self.matcher.calculate_similarity("ABC123", "ABC1Z3")
        self.assertGreater(similarity, 70)
        self.assertLess(similarity, 100)

    def test_calculate_similarity_empty(self):
        """Test empty string similarity."""
        similarity = self.matcher.calculate_similarity("", "ABC123")
        self.assertEqual(similarity, 0)

    def test_parse_timestamp_http_format(self):
        """Test HTTP date format parsing."""
        timestamp_str = "Wed, 21 Oct 2015 07:28:00 GMT"
        result = self.matcher.parse_timestamp(timestamp_str)

        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2015)
        self.assertEqual(result.month, 10)
        self.assertEqual(result.day, 21)

    def test_parse_timestamp_invalid(self):
        """Test invalid timestamp."""
        result = self.matcher.parse_timestamp("invalid_timestamp")
        self.assertIsNone(result)

    def test_calculate_time_diff_same_time(self):
        """Test time difference for same timestamp."""
        timestamp = "Wed, 21 Oct 2015 07:28:00 GMT"
        diff = self.matcher.calculate_time_diff_hours(timestamp, timestamp)

        self.assertIsNotNone(diff)
        self.assertEqual(diff, 0.0)

    def test_calculate_time_diff_hours(self):
        """Test time difference calculation."""
        time1 = "Wed, 21 Oct 2015 07:00:00 GMT"
        time2 = "Wed, 21 Oct 2015 10:00:00 GMT"  # 3 hours later

        diff = self.matcher.calculate_time_diff_hours(time1, time2)

        self.assertIsNotNone(diff)
        self.assertAlmostEqual(diff, 3.0, places=1)


class TestMatchingLogic(unittest.TestCase):
    """Test matching algorithm logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.matcher = VehicleMatcher(min_similarity=75)

    def test_find_best_match_exact(self):
        """Test finding exact match."""
        vehicle = {
            'id': 1,
            'plate_text': 'ABC123',
            'upload_time': 'Wed, 21 Oct 2015 07:00:00 GMT',
            'confidence': 0.9,
            'matched': False,
            'match_id': None
        }

        candidates = [
            {
                'id': 2,
                'plate_text': 'ABC123',  # Exact match
                'upload_time': 'Wed, 21 Oct 2015 08:00:00 GMT',
                'confidence': 0.9,
                'matched': False,
                'match_id': None
            },
            {
                'id': 3,
                'plate_text': 'XYZ789',  # Different
                'upload_time': 'Wed, 21 Oct 2015 09:00:00 GMT',
                'confidence': 0.9,
                'matched': False,
                'match_id': None
            }
        ]

        result = self.matcher.find_best_match(vehicle, candidates)

        self.assertIsNotNone(result)
        best_candidate, score = result
        self.assertEqual(best_candidate['id'], 2)

    def test_find_best_match_already_matched(self):
        """Test that already matched candidates are skipped."""
        vehicle = {
            'id': 1,
            'plate_text': 'ABC123',
            'upload_time': 'Wed, 21 Oct 2015 07:00:00 GMT',
            'confidence': 0.9,
            'matched': False,
            'match_id': None
        }

        candidates = [
            {
                'id': 2,
                'plate_text': 'ABC123',
                'upload_time': 'Wed, 21 Oct 2015 08:00:00 GMT',
                'confidence': 0.9,
                'matched': True,  # Already matched
                'match_id': 3
            }
        ]

        result = self.matcher.find_best_match(vehicle, candidates)
        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
