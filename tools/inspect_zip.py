import zipfile, re, collections, sys
z = zipfile.ZipFile(sys.argv[1])
names = [i for i in z.infolist() if not i.filename.endswith(".json") and not i.is_dir()]
base = lambda i: i.filename.rsplit("/", 1)[-1]
print("media files:", len(names), " total GB:", round(sum(i.file_size for i in names) / 1e9, 2))
mon = [i for i in names if re.search(r"screensh_12345678_", i.filename)]
print("monitor screenshots:", len(mon), " MB:", round(sum(i.file_size for i in mon) / 1e6, 1))
if mon:
    s = sorted(base(i) for i in mon)
    print("  first:", s[0], " last:", s[-1])
other = [base(i) for i in names if "12345678" in i.filename and i not in mon]
print("other files with 12345678:", len(other), other[:10])
pat = lambda n: re.sub(r"\d+.*", "#", n)
print("name patterns:", collections.Counter(pat(base(i)) for i in names).most_common(25))
vids = [base(i) for i in names if re.search(r"\.(mp4|mov|3gp|mkv|avi)$", i.filename, re.I)]
print("videos:", len(vids), collections.Counter(pat(v) for v in vids).most_common(15))
