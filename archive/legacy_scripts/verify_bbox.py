"""
Verify bbox extraction by downloading sample images and cropping license plates
"""

import sqlite3
import requests
from PIL import Image
from io import BytesIO
import os

def verify_bbox_sample(num_samples=3):
    """
    Download sample images and crop them using the extracted bbox
    """
    conn = sqlite3.connect('data/vehicle_metadata.db')
    cursor = conn.cursor()

    # Get sample records with bbox
    cursor.execute("""
        SELECT url, bbox_x, bbox_y, bbox_w, bbox_h
        FROM vehicle_metadata
        WHERE bbox_x IS NOT NULL
        LIMIT ?
    """, (num_samples,))

    samples = cursor.fetchall()
    conn.close()

    os.makedirs('data/bbox_verification', exist_ok=True)

    print(f"\nVerifying bbox extraction on {len(samples)} sample images...\n")

    for i, (url, x, y, w, h) in enumerate(samples, 1):
        try:
            print(f"Sample {i}: {url[-50:]}")
            print(f"  Downloading image...")

            # Download image
            response = requests.get(url, timeout=10)
            response.raise_for_status()

            # Open image
            img = Image.open(BytesIO(response.content))
            print(f"  Image size: {img.size[0]}x{img.size[1]}")
            print(f"  Bbox: x={x}, y={y}, w={w}, h={h}")

            # Crop using bbox
            cropped = img.crop((x, y, x + w, y + h))

            # Save full image
            full_path = f'data/bbox_verification/sample_{i}_full.jpg'
            img.save(full_path)

            # Save cropped license plate
            crop_path = f'data/bbox_verification/sample_{i}_plate.jpg'
            cropped.save(crop_path)

            print(f"  ✓ Saved: {crop_path}")
            print(f"  ✓ Plate size: {cropped.size[0]}x{cropped.size[1]}\n")

        except Exception as e:
            print(f"  ✗ Error: {e}\n")

    print(f"Verification complete! Check 'data/bbox_verification/' folder")


if __name__ == "__main__":
    verify_bbox_sample(3)
