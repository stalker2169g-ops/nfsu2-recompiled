#!/usr/bin/env python3
"""Patch only the SHA-pinned upstream ARM64 HLE entry points, not game code."""
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import lief
from elftools.elf.elffile import ELFFile
from native_codec_runner import NativeRunner

EXPECTED = "c9bbe1165105f135eea4a3287cf7f870a02d8d433a973002418dafb302993c2c"
source = Path(sys.argv[1])
data = source.read_bytes()
assert hashlib.sha256(data).hexdigest() == EXPECTED, "Unrecognized native runtime"
runner = NativeRunner(data)
bindings = runner.initialize()
del runner
elf = ELFFile(io.BytesIO(data))
symbols = {s.name: s for s in elf.get_section_by_name(".dynsym").iter_symbols()}
language_setter = symbols["_Z16setGuestLanguagePKc"]["st_value"]
assert language_setter == 0x487c20, "Unexpected language setter"
definitions = {n: symbols[n]["st_value"] for n in ("g_eax", "g_esp", "g_mem_base")}
definitions.update(guest_language=0x97e7de8, runtime_memory=0x97e7d10,
                   original_set_error=bindings["SetLastError"],
                   original_map_string=bindings["LCMapStringW"])
binary = lief.ELF.parse(str(source))
old_symbol_values = {n: binary.get_dynamic_symbol(n).value for n in definitions if n.startswith("g_")}
segment = lief.ELF.Segment()
segment.type = lief.ELF.Segment.TYPE.LOAD
segment.flags = lief.ELF.Segment.FLAGS.R | lief.ELF.Segment.FLAGS.X
segment.alignment = 0x4000
segment.virtual_address = (max(s.virtual_address + s.virtual_size for s in binary.segments) + 0x1ffff) & ~0xffff
segment.physical_address = segment.virtual_address
segment.content = [0] * 65536
added = binary.add(segment)
for name, value in old_symbol_values.items():
    assert binary.get_dynamic_symbol(name).value == value, "ELF addition moved existing code/data"
va = added.virtual_address
work = Path("build/russian-codec")
work.mkdir(parents=True, exist_ok=True)
header = []
for cp in (1251, 1252, 437):
    values = [ord(bytes([b]).decode("cp" + str(cp), errors="replace")) for b in range(256)]
    header.append("static const uint16_t table_" + str(cp) + "[256]={" +
                  ",".join(hex(v) for v in values) + "};")
(work / "cp_tables.h").write_text("\n".join(header))
ndk = Path(os.environ["ANDROID_HOME"]) / "ndk/28.2.13676358/toolchains/llvm/prebuilt/linux-x86_64/bin"
subprocess.run([str(ndk / "aarch64-linux-android29-clang"), "-O2", "-std=c11",
                "-ffreestanding", "-fno-builtin", "-fno-pic", "-fno-pie",
                "-fno-stack-protector", "-fno-unwind-tables", "-fno-asynchronous-unwind-tables",
                "-fvisibility=hidden", "-Wall", "-Wextra", "-Werror",
                "-I" + str(work), "-c", "ports/russian_arm64/native_cp1251.c",
                "-o", str(work / "codec.o")], check=True)
obj = ELFFile(io.BytesIO((work / "codec.o").read_bytes()))
for sec in obj.iter_sections():
    if sec["sh_type"] == "SHT_RELA":
        for rel in sec.iter_relocations():
            assert rel["r_info_type"] != 257, "Absolute pointer relocation would break ASLR"
(work / "codec.ld").write_text(
    "SECTIONS { . = " + hex(va) + "; .patch : { *(.text*) *(.rodata*) } "
    "/DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) } }")
command = [str(ndk / "ld.lld"), "--no-relax", "--no-undefined", "-T", str(work / "codec.ld")]
command += ["--defsym=" + name + "=" + hex(value) for name, value in definitions.items()]
command += [str(work / "codec.o"), "-o", str(work / "codec.elf")]
subprocess.run(command, check=True)
patch_elf = ELFFile(io.BytesIO((work / "codec.elf").read_bytes()))
patch = patch_elf.get_section_by_name(".patch").data()
assert len(patch) <= 65536, "Codec does not fit reserved segment"
targets = {s.name: s["st_value"] for s in patch_elf.get_section_by_name(".symtab").iter_symbols()}
binary.patch_address(va, list(patch))

def jump(at, target):
    pages = ((target & ~0xfff) - (at & ~0xfff)) >> 12
    assert -(1 << 20) <= pages < 1 << 20
    immediate = pages & 0x1fffff
    adrp = 0x90000010 | ((immediate & 3) << 29) | ((immediate >> 2) << 5)
    add = 0x91000210 | ((target & 0xfff) << 10)
    return struct.pack("<III", adrp, add, 0xd61f0200)

replacements = {
    "GetACP": "ru_get_acp", "GetThreadLocale": "ru_thread_locale",
    "GetCPInfo": "ru_cp_info", "MultiByteToWideChar": "ru_multi_to_wide",
    "WideCharToMultiByte": "ru_wide_to_multi", "LCMapStringW": "ru_map_string"
}
report = {"input_sha256": EXPECTED, "segment_va": va, "definitions": definitions,
          "bindings": bindings, "language_setter": language_setter, "replacements": {}}
for name, function in replacements.items():
    address = bindings[name]
    assert len(binary.get_content_from_virtual_address(address, 12)) == 12
    binary.patch_address(address, list(jump(address, targets[function])))
    report["replacements"][name] = {"entry": address, "replacement": targets[function]}
binary.patch_address(language_setter, list(jump(language_setter, targets["ru_set_language"])))
binary.write(str(source))
patched = ELFFile(io.BytesIO(source.read_bytes()))
patched_symbols = {s.name: s["st_value"] for s in patched.get_section_by_name(".dynsym").iter_symbols()}
for name, value in old_symbol_values.items():
    assert patched_symbols[name] == value, "Written ELF changed runtime ABI"
report["output_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
(work / "patch-report.json").write_text(json.dumps(report, indent=2))
print("Native CP1251 replacement injected:", report["output_sha256"], flush=True)
