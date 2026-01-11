# 🚀 Quick Reference Guide

## Running the System

### Complete Pipeline
```bash
python main.py --input vehicle_images_input.txt --output submission.txt
```

### Individual Phases
```bash
# Phase 1: Metadata extraction
python main.py --phase metadata --input vehicle_images_input.txt

# Phase 2: OCR extraction
python main.py --phase ocr

# Phase 3: Matching
python main.py --phase matching

# Phase 4: Export
python main.py --phase export --output submission.txt
```

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | Main entry point, runs all phases |
| `configs/config.yaml` | Configuration (thresholds, parameters) |
| `src/data/metadata_extractor.py` | Async metadata & bbox extraction |
| `src/ocr/alpr_engine.py` | Multi-engine OCR with enhancements |
| `src/matching/vehicle_matcher.py` | Fuzzy temporal matching |
| `src/utils/text_normalizer.py` | Character normalization (0/O, 1/I) |
| `src/utils/logger.py` | Logging setup |
| `src/utils/config_loader.py` | YAML config loader |

## Module Import Paths

```python
# Configuration
from src.utils.config_loader import ConfigLoader
config = ConfigLoader('configs/config.yaml')

# Logging
from src.utils.logger import setup_logger
logger = setup_logger("module_name", log_file="logs/app.log")

# Metadata Extraction
from src.data.metadata_extractor import MetadataExtractor
extractor = MetadataExtractor(db_path="data/metadata.db")

# OCR
from src.ocr.alpr_engine import ALPREngine
alpr = ALPREngine(fast_alpr_enabled=True, easyocr_enabled=True)

# Matching
from src.matching.vehicle_matcher import VehicleMatcher
matcher = VehicleMatcher(min_similarity=75, max_time_diff_hours=72)

# Text Normalization
from src.utils.text_normalizer import TextNormalizer
normalizer = TextNormalizer()
normalized = normalizer.normalize("ABC-123")
variants = normalizer.generate_variants("ABC123")
```

## Configuration Quick Edit

Edit `configs/config.yaml`:

```yaml
# Matching parameters
matching:
  min_similarity_threshold: 75    # Lower = more matches (less strict)
  max_time_difference_hours: 72   # Increase for wider time window

# OCR parameters
ocr:
  fast_alpr:
    confidence_threshold: 0.5     # Lower = accept lower confidence
  easyocr:
    confidence_threshold: 0.4

# Logging
logging:
  level: "INFO"                   # DEBUG for verbose output
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_text_normalizer.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

## Git Workflow

```bash
# Stage changes
git add src/ configs/ tests/ main.py README.md requirements.txt .gitignore LICENSE

# Commit
git commit -m "refactor: transform into production-grade ML portfolio"

# Push
git push -u origin main
```

## Troubleshooting

### Import Errors
```bash
# Ensure src is in Python path
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### Missing Dependencies
```bash
pip install -r requirements.txt
pip install 'fast-alpr[onnx]'
```

### Database Errors
```bash
# Recreate database
rm data/vehicle_metadata.db
python main.py --phase metadata
```

## Performance Tuning

### Increase Concurrency
Edit `configs/config.yaml`:
```yaml
image_processing:
  max_concurrent_downloads: 50  # Increase from 30
```

### Lower Matching Threshold
```yaml
matching:
  min_similarity_threshold: 70  # Lower from 75 for more matches
```

### Adjust OCR Confidence
```yaml
ocr:
  fast_alpr:
    confidence_threshold: 0.3   # Lower from 0.5
```

---

**Need help?** Check `REFACTORING_SUMMARY.md` or `GIT_COMMIT_GUIDE.md`
