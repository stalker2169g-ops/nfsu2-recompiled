#!/usr/bin/env python3
"""Check the production single-byte codec against Python's CP1251 reference."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
codec = (root / "android/app/src/main/cpp/guest_charset.inc").read_text()
codec = codec.split("void wideToMulti()")[0]
expected = [ord(bytes([i]).decode("cp1251", errors="replace")) for i in range(256)]
source = (
    '#include <cstdint>\n#include <string>\n#include <cassert>\n'
    'std::string guestLanguage="Russian";\n' + codec +
    '\nint main(){\nconst uint32_t expected[]={' + ",".join(map(str, expected)) + '};\n'
    'for(unsigned i=0;i<256;++i){assert(decodeByte(1251,i)==expected[i]);'
    'assert(encodeByte(1251,expected[i])==int(i));}\n'
    'assert(effectiveCP(0)==1251); assert(effectiveCP(3)==1251);'
    'assert(effectiveCP(1)==437); assert(effectiveCP(1252)==1252);'
    'assert(encodeByte(1251,0x1f600)==-1);'
    'guestLanguage="Spanish"; assert(effectiveCP(0)==1252);'
    'assert(decodeByte(1252,0xe9)==0xe9);'
    'assert(decodeByte(1252,0x80)==0x20ac);}\n'
)
with tempfile.TemporaryDirectory() as directory:
    cpp = Path(directory) / "check.cpp"
    binary = Path(directory) / "check"
    cpp.write_text(source)
    subprocess.run([os.environ.get("CXX", "c++"), "-std=c++17", "-Wall", "-Wextra",
                    "-Werror", str(cpp), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
print("PASS: CP1251 byte mapping, reverse mapping, ACP selection and CP1252 regression")
