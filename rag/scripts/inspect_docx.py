import re
import sys
import zipfile

path = sys.argv[1]
xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")

print("file:", path)
print("tracked insertions :", len(re.findall(r"<w:ins\b", xml)))
print("tracked deletions  :", len(re.findall(r"<w:del\b", xml)))
print("hidden text runs   :", len(re.findall(r"<w:vanish\b", xml)))
print("comments part      :", "word/comments.xml" in zipfile.ZipFile(path).namelist())

print("\nDELETED text:")
for block in re.findall(r"<w:del\b.*?</w:del>", xml, flags=re.S):
    print(" -", "".join(re.findall(r"<w:delText[^>]*>(.*?)</w:delText>", block)))

print("\nINSERTED text:")
for block in re.findall(r"<w:ins\b.*?</w:ins>", xml, flags=re.S):
    print(" -", "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", block)))

print("\nHIDDEN text:")
for run in re.findall(r"<w:r\b(?:(?!</w:r>).)*?<w:vanish\b.*?</w:r>", xml, flags=re.S):
    print(" -", "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", run)))