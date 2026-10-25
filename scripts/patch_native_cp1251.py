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
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
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
                   original_error_entry=bindings["SetLastError"],
                   original_map_continuation=bindings["LCMapStringW"]+12)
# Add a new load segment without moving any original bytes or virtual addresses.
# The enlarged program-header table lives in the last page of that segment.
original_symbols = {n: symbols[n]["st_value"] for n in definitions if n.startswith("g_")}
va = (max(s["p_vaddr"] + s["p_memsz"] for s in elf.iter_segments()
          if s["p_type"] == "PT_LOAD") + 0x3fff) & ~0x3fff
new_offset = (len(data) + 0x3fff) & ~0x3fff
output = bytearray(data)
output.extend(bytes(new_offset + 65536 - len(output)))
phoff, phentsize, phnum = elf["e_phoff"], elf["e_phentsize"], elf["e_phnum"]
assert phentsize == 56 and (phnum+1)*56 <= 4096
headers = []
new_phoff = new_offset + 0xf000
for i in range(phnum):
    fields = list(struct.unpack_from("<IIQQQQQQ", data, phoff+i*56))
    if fields[0] == 6:  # PT_PHDR
        fields[2:7] = [new_phoff, va+0xf000, va+0xf000, (phnum+1)*56, (phnum+1)*56]
    headers.append(struct.pack("<IIQQQQQQ",*fields))
headers.append(struct.pack("<IIQQQQQQ",1,5,new_offset,va,va,65536,65536,0x4000))
output[new_phoff:new_phoff+(phnum+1)*56] = b"".join(headers)
struct.pack_into("<Q",output,32,new_phoff)
struct.pack_into("<H",output,56,phnum+1)
def file_offset(address):
    for seg in elf.iter_segments():
        if seg["p_type"]=="PT_LOAD" and seg["p_vaddr"]<=address<seg["p_vaddr"]+seg["p_filesz"]:
            return seg["p_offset"]+address-seg["p_vaddr"]
    raise ValueError("Unmapped patch address "+hex(address))
work = Path("build/russian-codec")
work.mkdir(parents=True, exist_ok=True)
header = []
for cp in (1251, 1252, 437):
    values = [ord(bytes([b]).decode("cp" + str(cp), errors="replace")) for b in range(256)]
    if cp == 1252:
        values = [b if value == 0xfffd else value for b, value in enumerate(values)]
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
# Preserve the three overwritten, PC-independent frame-setup instructions.
map_entry = bindings["LCMapStringW"]
original_prefix = data[file_offset(map_entry):file_offset(map_entry)+12]
instructions = list(Cs(CS_ARCH_ARM64, CS_MODE_ARM).disasm(original_prefix, map_entry))
assert len(instructions)==3 and all(i.mnemonic in ("sub","stp","mov","add") for i in instructions), "LCMap prologue requires relocation review"
assembly = ".text\n.global original_map_string\n.type original_map_string,%function\noriginal_map_string:\n"
assembly += "".join(".inst " + hex(word) + "\n" for word in struct.unpack("<3I",original_prefix))
assembly += "adrp x16, original_map_continuation\nadd x16,x16,:lo12:original_map_continuation\nbr x16\n"
assembly += ".global original_set_error\n.type original_set_error,%function\noriginal_set_error:\n"
assembly += "adrp x16, original_error_entry\nadd x16,x16,:lo12:original_error_entry\nbr x16\n"
(work / "trampoline.S").write_text(assembly)
subprocess.run([str(ndk / "aarch64-linux-android29-clang"), "-c", str(work / "trampoline.S"), "-o", str(work / "trampoline.o")],check=True)
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
command += [str(work / "codec.o"), str(work / "trampoline.o"), "-o", str(work / "codec.elf")]
subprocess.run(command, check=True)
patch_elf = ELFFile(io.BytesIO((work / "codec.elf").read_bytes()))
assert not any("AbsLongThunk" in s.name for s in patch_elf.get_section_by_name(".symtab").iter_symbols()), "Absolute linker thunk would break ASLR"
patch = patch_elf.get_section_by_name(".patch").data()
assert len(patch) <= 0xf000, "Codec does not fit reserved segment"
targets = {s.name: s["st_value"] for s in patch_elf.get_section_by_name(".symtab").iter_symbols()}
output[new_offset:new_offset+len(patch)] = patch

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
    at = file_offset(address)
    output[at:at+12] = jump(address, targets[function])
    report["replacements"][name] = {"entry": address, "replacement": targets[function]}
at = file_offset(language_setter)
output[at:at+12] = jump(language_setter, targets["ru_set_language"])
source.write_bytes(output)
patched = ELFFile(io.BytesIO(source.read_bytes()))
patched_symbols = {s.name: s["st_value"] for s in patched.get_section_by_name(".dynsym").iter_symbols()}
for name, value in original_symbols.items():
    assert patched_symbols[name] == value, "Written ELF changed runtime ABI"
report["output_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
(work / "patch-report.json").write_text(json.dumps(report, indent=2))
print("Native CP1251 replacement injected:", report["output_sha256"], flush=True)
