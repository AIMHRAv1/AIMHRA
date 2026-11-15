Real phone photos for OCR evaluation.

Drop photos here:
  real_photos/dev/   <- use these when tuning (dev split)
  real_photos/test/  <- held out; only run AFTER tuning is finished

Each photo needs a ground-truth JSON file with the same base name:
  IMG_001.jpg
  IMG_001.json     {"fields": {"age": 28, "body_temperature": 98.6, ...}}

Photos without a .json file are skipped with a warning (no way to score them).
Values must be exactly what is PRINTED on the card.
