"""OCR model training package.

Uses report/reports (PDF text layer + rendered PNG) as a labeled corpus to
fine-tune the EasyOCR recognition model (gen2 VGG+BiLSTM+CTC, english_g2
starting weights) on this project's report layouts. GPU (CUDA) is required
for training; see management commands ocr_build_crops and ocr_train.
"""
