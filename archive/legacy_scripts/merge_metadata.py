"""
Merge bbox_export.json into metadata_export.json for a unified metadata file
"""

import sqlite3
import json

def export_complete_metadata():
    """
    Export all metadata including bbox to a single comprehensive JSON file
    """
    conn = sqlite3.connect('data/vehicle_metadata.db')
    cursor = conn.cursor()

    # Get all fields from the database
    cursor.execute("""
        SELECT
            id, url, upload_time, last_modified, content_type, content_length,
            bbox_x, bbox_y, bbox_w, bbox_h,
            extraction_timestamp, status
        FROM vehicle_metadata
        ORDER BY id
    """)

    columns = [
        'id', 'url', 'upload_time', 'last_modified', 'content_type', 'content_length',
        'bbox_x', 'bbox_y', 'bbox_w', 'bbox_h',
        'extraction_timestamp', 'status'
    ]

    rows = cursor.fetchall()

    # Convert to list of dicts
    complete_data = []
    for row in rows:
        record = dict(zip(columns, row))

        # Add bbox object for easier access (if bbox exists)
        if record['bbox_x'] is not None:
            record['bbox'] = {
                'x': record['bbox_x'],
                'y': record['bbox_y'],
                'width': record['bbox_w'],
                'height': record['bbox_h']
            }
        else:
            record['bbox'] = None

        complete_data.append(record)

    conn.close()

    # Save to JSON
    output_path = 'data/metadata_export.json'
    with open(output_path, 'w') as f:
        json.dump(complete_data, f, indent=2)

    print(f"✓ Exported {len(complete_data)} complete records to {output_path}")

    # Statistics
    with_bbox = sum(1 for r in complete_data if r['bbox'] is not None)
    print(f"  - Records with bbox: {with_bbox}/{len(complete_data)} ({with_bbox/len(complete_data)*100:.1f}%)")

    return len(complete_data), with_bbox


if __name__ == "__main__":
    print("\nMerging metadata and bbox data into single file...\n")
    total, with_bbox = export_complete_metadata()
    print(f"\n✓ Complete! metadata_export.json now contains all data.")
    print(f"  - You can now delete bbox_export.json (no longer needed)\n")
