#!/usr/bin/env python3
"""Load the pinned Android ELF in Unicorn to inspect guest HLE bindings.
External host services are deliberately stubbed; this does not test Android
startup, Vulkan, game assets, or rendering.
"""
import io
import json
import struct
import sys
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UcError, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import *

class NativeRunner:
    STOP = 0x21000000
    def __init__(self, data):
        self.data = data
        self.elf = ELFFile(io.BytesIO(data))
        self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.symbols = {s.name: s for s in self.elf.get_section_by_name(".dynsym").iter_symbols()}
        top = max(s["p_vaddr"] + s["p_memsz"] for s in self.elf.iter_segments() if s["p_type"] == "PT_LOAD")
        self.uc.mem_map(0, (top + 0xffff) & ~0xffff)
        for seg in self.elf.iter_segments():
            if seg["p_type"] == "PT_LOAD":
                self.uc.mem_write(seg["p_vaddr"], seg.data())
        self.uc.mem_map(0x20000000, 0x100000)
        self.uc.mem_map(self.STOP, 0x1000)
        self.uc.mem_map(0x30000000, 0x200000)
        for seg in self.elf.iter_segments():
            if seg['p_type'] == 'PT_TLS':
                self.uc.mem_write(0x30001000, seg.data())
        self.uc.mem_map(0x40000000, 0x800000)
        self.uc.mem_map(0x50000000, 0x4000000)
        self.uc.reg_write(UC_ARM64_REG_TPIDR_EL0, 0x30000000)
        self.uc.reg_write(UC_ARM64_REG_CPACR_EL1, 3 << 20)
        self.stubs = {}
        self.allocations = {}
        self.next_heap = 0x50000000
        self.tls = {}
        self.callback_returns = {}
        self.uc.hook_add(UC_HOOK_CODE, self.on_stub, begin=0x20000000, end=0x200fffff)
        for sec in self.elf.iter_sections():
            if sec["sh_type"] != "SHT_RELA":
                continue
            table = self.elf.get_section(sec["sh_link"])
            for rel in sec.iter_relocations():
                kind, at = rel["r_info_type"], rel["r_offset"]
                if kind == 1027:
                    value = rel["r_addend"]
                elif kind in (257, 1025, 1026):
                    sym = table.get_symbol(rel["r_info_sym"])
                    value = sym["st_value"]
                    if sym["st_shndx"] == "SHN_UNDEF":
                        value = self.stub(sym.name)
                    value += rel["r_addend"]
                elif kind == 1031:
                    sym = table.get_symbol(rel["r_info_sym"])
                    offset = 0x1000 + sym["st_value"] + rel["r_addend"]
                    self.put64(at, self.stub("__tlsdesc_resolver"))
                    self.put64(at + 8, offset)
                    continue
                else:
                    raise RuntimeError("Unsupported relocation " + str(kind))
                self.put64(at, value)

    def u64(self, p):
        return struct.unpack("<Q", self.uc.mem_read(p, 8))[0]
    def put64(self, p, v):
        self.uc.mem_write(p, struct.pack("<Q", v & 0xffffffffffffffff))
    def allocate(self, size):
        size = max(16, (int(size) + 15) & ~15)
        at = self.next_heap
        self.next_heap += size
        if self.next_heap > 0x54000000:
            raise RuntimeError("Emulated heap exhausted")
        self.allocations[at] = size
        return at
    def string(self, p, limit=65536):
        if not p:
            return b""
        out = bytearray()
        while len(out) < limit:
            value = self.uc.mem_read(p + len(out), 1)[0]
            if not value:
                return bytes(out)
            out.append(value)
        raise RuntimeError("Unterminated string")
    def stub(self, name):
        for at, known in self.stubs.items():
            if known == name:
                return at
        at = 0x20000000 + len(self.stubs) * 16
        self.stubs[at] = name
        self.uc.mem_write(at, bytes.fromhex("c0035fd6"))
        return at

    def on_stub(self, uc, address, size, _):
        name = self.stubs.get(address)
        if name is None:
            raise RuntimeError("Unknown stub " + hex(address))
        args = [uc.reg_read(r) for r in (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3)]
        a, b, c, d = args
        result = 0
        if name == "__tlsdesc_resolver":
            result = self.u64(a + 8)
        elif name in ("malloc", "_Znwm", "_Znam"):
            result = self.allocate(a)
        elif name == "calloc":
            result = self.allocate(a * b)
        elif name == "realloc":
            result = self.allocate(b)
            if a:
                uc.mem_write(result, bytes(uc.mem_read(a, min(self.allocations.get(a, 0), b))))
        elif name == "free":
            pass
        elif name in ("memcpy", "memmove", "__memcpy_chk", "__memmove_chk"):
            uc.mem_write(a, bytes(uc.mem_read(b, c)))
            result = a
        elif name in ("memset", "__memset_chk"):
            uc.mem_write(a, bytes([b & 255]) * c)
            result = a
        elif name == "strlen":
            result = len(self.string(a))
        elif name == "strnlen":
            result = len(self.string(a)[:b])
        elif name in ("strcmp", "strncmp", "memcmp", "bcmp"):
            if name in ("memcmp", "bcmp"):
                left, right = bytes(uc.mem_read(a, c)), bytes(uc.mem_read(b, c))
            else:
                left, right = self.string(a), self.string(b)
                if name == "strncmp":
                    left, right = left[:c], right[:c]
            result = (left > right) - (left < right)
        elif name == "__emutls_get_address":
            if a not in self.tls:
                n, align, _, template = struct.unpack("<4Q", uc.mem_read(a, 32))
                self.tls[a] = self.allocate(n)
                if template:
                    uc.mem_write(self.tls[a], bytes(uc.mem_read(template, n)))
            result = self.tls[a]
        elif name == "__cxa_guard_acquire":
            result = int(uc.mem_read(a, 1)[0] == 0)
        elif name == "__cxa_guard_release":
            uc.mem_write(a, b"\1")
        elif name == "__system_property_get":
            uc.mem_write(b, b"\0")
        elif name in ("__cxa_atexit", "__cxa_finalize", "__register_atfork",
                      "pthread_mutex_init", "pthread_mutex_lock", "pthread_mutex_unlock",
                      "pthread_mutex_destroy", "pthread_cond_init", "pthread_cond_destroy",
                      "pthread_rwlock_init", "__android_log_print", "__android_log_write"):
            pass
        elif name in ("getenv", "getauxval"):
            pass
        else:
            raise RuntimeError("Host stub required: " + name + " caller " + hex(uc.reg_read(UC_ARM64_REG_LR)))
        uc.reg_write(UC_ARM64_REG_X0, result & 0xffffffffffffffff)
        uc.reg_write(UC_ARM64_REG_PC, uc.reg_read(UC_ARM64_REG_LR))

    def call(self, address, *args, count=20000000):
        self.uc.reg_write(UC_ARM64_REG_SP, 0x407fff00)
        self.uc.reg_write(UC_ARM64_REG_LR, self.STOP)
        for i, arg in enumerate(args):
            self.uc.reg_write(UC_ARM64_REG_X0 + i, arg)
        self.uc.emu_start(address, self.STOP, count=count)
        if self.uc.reg_read(UC_ARM64_REG_PC) != self.STOP:
            raise RuntimeError("Execution limit at " + hex(self.uc.reg_read(UC_ARM64_REG_PC)))
        return self.uc.reg_read(UC_ARM64_REG_X0)

    def bindings(self):
        names = ("GetACP", "GetThreadLocale", "GetCPInfo", "SetLastError",
                 "GetLastError", "MultiByteToWideChar", "WideCharToMultiByte", "LCMapStringW")
        out = {}
        for start, size in self.allocations.items():
            block = bytes(self.uc.mem_read(start, size))
            for name in names:
                needle = bytes([len(name) * 2]) + name.encode() + b"\0"
                at = block.find(needle)
                if at >= 0 and at + 32 <= size:
                    fn = struct.unpack_from("<Q", block, at + 24)[0]
                    if 0x440000 <= fn < 0xa000000:
                        out[name] = fn
        return out

    def initialize(self):
        section = self.elf.get_section_by_name(".init_array")
        values = struct.unpack("<" + "Q" * (section["sh_size"] // 8),
                               self.uc.mem_read(section["sh_addr"], section["sh_size"]))
        print("Initializers:", [hex(x) for x in values], flush=True)
        for i, address in enumerate(values):
            # Only initialize guest HLE maps; renderer/libc++ process startup is outside this test.
            if address != 0x4a1ffc:
                continue
            print("Initializing guest HLE", i, hex(address), flush=True)
            self.call(address)
            found = self.bindings()
            print("Bindings", {k: hex(v) for k, v in found.items()}, flush=True)
            if len(found) == 8:
                return found
        raise RuntimeError("Guest codec bindings were not initialized")

if __name__ == "__main__":
    runner = NativeRunner(Path(sys.argv[1] if len(sys.argv) > 1 else "native.so").read_bytes())
    bindings = runner.initialize()
    print("NATIVE_BINDINGS=" + json.dumps(bindings), flush=True)
