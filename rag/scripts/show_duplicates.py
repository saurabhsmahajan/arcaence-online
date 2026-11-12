from ingest.duplicates import compare
from ingest.normalize import build_records

print(f"{'document A':<22}{'document B':<22}{'exact':<7}{'jaccard':<9}containment")
for p in compare(build_records()):
    if p["containment"] >= 0.15:
        print(f"{p['a']:<22}{p['b']:<22}{str(p['exact']):<7}{p['jaccard']:<9.2f}{p['containment']:.2f}")