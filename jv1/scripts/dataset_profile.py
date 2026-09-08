"""Quick dataset profile without pandas (csv + statistics only)."""
import csv, statistics, hashlib, os
from collections import Counter

PATH = r"D:\project\AIMHRA\AIMHRA\v1\Mathernal_Risk.csv"

with open(PATH, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.DictReader(f))

cols = list(rows[0].keys())
print(f"ROWS: {len(rows)}")
print(f"COLUMNS ({len(cols)}): {cols}")
print(f"MD5: {hashlib.md5(open(PATH,'rb').read()).hexdigest()}")

# normalize headers note
for c in cols:
    if c != c.strip():
        print(f"NOTE: column with surrounding whitespace: {c!r} -> {c.strip()!r}")

target = [c for c in cols if c.strip().lower() in ("status", "risk", "risklevel", "risk level")][0]
labels = Counter(r[target].strip().lower() for r in rows)
print(f"CLASS DISTRIBUTION ({target}): {dict(labels)}")
print(f"MISSING per column: " + ", ".join(f"{c.strip()}={sum(1 for r in rows if not r[c].strip())}" for c in cols))

# duplicates on feature columns (excluding ID/Name/target)
feat_cols = [c for c in cols if c.strip() not in ("Patient ID", "Name", target)]
seen, dup_full = set(), 0
for r in rows:
    key = tuple(r[c].strip() for c in feat_cols) + (r[target].strip(),)
    if key in seen:
        dup_full += 1
    seen.add(key)
print(f"EXACT DUPLICATE ROWS (features+label, excluding ID/Name): {dup_full}")

# numeric ranges
for c in feat_cols:
    vals = []
    bad = 0
    for r in rows:
        s = r[c].strip()
        try:
            vals.append(float(s))
        except ValueError:
            bad += 1
    if bad == 0:
        print(f"NUM {c.strip()}: min={min(vals)}, max={max(vals)}, mean={statistics.mean(vals):.2f}, unique={len(set(vals))}")
    else:
        print(f"NON-NUM {c.strip()}: non-numeric={bad}, unique={len(set(r[c].strip() for r in rows))}")

# ID / Name uniqueness
pid = [r["Patient ID"].strip() for r in rows]
names = [r["Name"].strip() for r in rows]
print(f"Patient ID unique: {len(set(pid))}/{len(pid)}")
print(f"Name unique values: {len(set(names))}")

# duplicate Patient IDs with conflicting labels?
from collections import defaultdict
by_id = defaultdict(set)
for r in rows:
    by_id[r["Patient ID"].strip()].add(r[target].strip().lower())
conf = {k: v for k, v in by_id.items() if len(v) > 1}
print(f"Patient IDs with conflicting labels: {len(conf)}")
