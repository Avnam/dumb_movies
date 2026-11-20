"""List what's inside a zip of photos/videos (e.g. a Google Takeout export).

Usage: python tools/inspect_zip.py ZIP [--pattern REGEX]

Shows the common file-name patterns (digits replaced by #), how many videos there
are, and - with --pattern - how many files match and their first/last names.
"""
import argparse, collections, re, zipfile

ap = argparse.ArgumentParser()
ap.add_argument("zip")
ap.add_argument("--pattern", help="regex to count matching file names")
a = ap.parse_args()

z = zipfile.ZipFile(a.zip)
names = [i for i in z.infolist() if not i.filename.endswith(".json") and not i.is_dir()]
base = lambda i: i.filename.rsplit("/", 1)[-1]
pat = lambda n: re.sub(r"\d+", "#", n)

print("media files:", len(names), " total GB:", round(sum(i.file_size for i in names) / 1e9, 2))
print("name patterns:")
for p, n in collections.Counter(pat(base(i)) for i in names).most_common(25):
    print(f"  {n:6d}  {p}")
vids = [base(i) for i in names if re.search(r"\.(mp4|mov|m4v|3gp|mkv|avi)$", i.filename, re.I)]
print("videos:", len(vids))
if a.pattern:
    hit = sorted(base(i) for i in names if re.search(a.pattern, base(i), re.I))
    mb = sum(i.file_size for i in names if re.search(a.pattern, base(i), re.I)) / 1e6
    print(f"matching {a.pattern!r}: {len(hit)} files, {mb:.1f} MB")
    if hit:
        print("  first:", hit[0], " last:", hit[-1])
