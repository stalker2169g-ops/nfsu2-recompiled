#!/usr/bin/env python3
"""Execute the actual pinned/patched ARM64 HLE, including stdcall cleanup.
Host allocator/log/math stubs are in native_codec_runner; no game/device rendering is emulated.
"""
import gc
import hashlib
import json
from pathlib import Path
import struct
import sys
from native_codec_runner import NativeRunner

class Codec:
    def __init__(self, path, base=0):
        self.runner=NativeRunner(Path(path).read_bytes(),base)
        self.base=base
        self.bindings=self.runner.initialize()
        self.uc=self.runner.uc
        self.uc.mem_map(0x100000000,0x800000)
        self.global_address=lambda name:base+self.runner.symbols[name]["st_value"]
        self.runner.put64(self.global_address("g_mem_base"),0x100000000)
        # GuestMemory::address uses its first field (the reserved base pointer).
        # Emulate that real object layout; no guest page/protection API is used here.
        memory_object=self.runner.allocate(128)
        self.runner.put64(memory_object,0x100000000)
        self.runner.put64(self.base+0x97e7d10,memory_object)
        initial=bytes(self.uc.mem_read(self.base+0x97e7de8,24))
        assert initial[0]==14 and initial[1:8]==b"Spanish",initial
    def write(self,address,data):
        self.uc.mem_write(0x100000000+address,data)
    def read(self,address,count):
        return bytes(self.uc.mem_read(0x100000000+address,count))
    def hle(self,name,*args):
        self.write(0x700000,struct.pack("<"+"I"*(1+len(args)),0x12345678,*[a&0xffffffff for a in args]))
        self.uc.mem_write(self.global_address("g_esp"),struct.pack("<I",0x700000))
        self.runner.call(self.bindings[name])
        stack=struct.unpack("<I",self.uc.mem_read(self.global_address("g_esp"),4))[0]
        assert stack==0x700000+4+len(args)*4,(name,hex(stack))
        return struct.unpack("<I",self.uc.mem_read(self.global_address("g_eax"),4))[0]
    def language(self,name):
        raw=name.encode()+b"\0"
        address=self.runner.allocate(len(raw))
        self.uc.mem_write(address,raw)
        sym=self.runner.symbols["_Z16setGuestLanguagePKc"]["st_value"]
        memory_object=self.runner.u64(self.base+0x97e7d10)
        self.runner.put64(self.base+0x97e7d10,0)
        self.runner.call(self.base+sym,address)
        self.runner.put64(self.base+0x97e7d10,memory_object)
        obj=bytes(self.uc.mem_read(self.base+0x97e7de8,24))
        assert obj[0]==len(name)*2 and obj[1:1+len(name)]==name.encode(),obj
    def multi(self,data,cp=1251,flags=0,terminated=False):
        self.write(0x1000,data)
        count=-1 if terminated else len(data)
        required=self.hle("MultiByteToWideChar",cp,flags,0x1000,count,0,0)
        assert required>0
        assert self.hle("MultiByteToWideChar",cp,flags,0x1000,count,0x2000,required)==required
        return self.read(0x2000,required*2).decode("utf-16le")
    def wide(self,text,cp=1251,flags=0,terminated=False,used=False,default=0):
        data=text.encode("utf-16le")
        self.write(0x1000,data)
        count=-1 if terminated else len(data)//2
        required=self.hle("WideCharToMultiByte",cp,flags,0x1000,count,0,0,default,0x4000 if used else 0)
        assert required>0
        assert self.hle("WideCharToMultiByte",cp,flags,0x1000,count,0x2000,required,default,0x4000 if used else 0)==required
        return self.read(0x2000,required)

def baseline(path):
    test=Codec(path)
    test.write(0x1000,b"\xcf\xf0\xe8\xe2\xe5\xf2\0")
    assert test.hle("MultiByteToWideChar",1251,0,0x1000,-1,0x2000,32)==0
    assert test.hle("GetLastError")==87
    print("BASELINE CONFIRMED: original ARM64 library rejects CP1251 with error 87",flush=True)

def patched(path,base):
    t=Codec(path,base)
    t.language("Russian")
    assert t.hle("GetACP")==1251
    assert t.hle("GetThreadLocale")==0x419
    assert t.hle("GetCPInfo",1251,0x3000)==1
    assert struct.unpack("<I",t.read(0x3000,4))[0]==1
    assert t.read(0x3004,2)==b"?\0"
    alphabet="АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ абвгдеёжзийклмнопрстуфхцчшщъыьэюя №"
    assert t.multi(alphabet.encode("cp1251"))==alphabet
    assert t.wide(alphabet)==alphabet.encode("cp1251")
    assert t.multi(b"\xcf\xf0\xe8\xe2\xe5\xf2\0",cp=0,terminated=True)=="Привет\0"
    assert t.wide("Ёжик\0",cp=0,terminated=True)=="Ёжик\0".encode("cp1251")
    for cp in (1251,437):
        data=bytes(range(256))
        assert t.multi(data,cp)==data.decode("cp"+str(cp),errors="replace")
    western=bytes(range(256))
    expected="".join(chr(b) if ch=="�" else ch for b,ch in enumerate(western.decode("cp1252",errors="replace")))
    assert t.multi(western,1252)==expected
    assert t.multi("Привет 😀".encode(),65001)=="Привет 😀"
    assert t.wide("Привет 😀",65001)=="Привет 😀".encode()
    t.write(0x1000,b"\xcf\xf0")
    t.write(0x2000,b"Z"*32)
    assert t.hle("MultiByteToWideChar",1251,0,0x1000,2,0x2000,1)==0
    assert t.hle("GetLastError")==122
    assert t.read(0x2000,32)==b"Z"*32
    t.write(0x1000,b"\xff")
    assert t.hle("MultiByteToWideChar",65001,8,0x1000,1,0x2000,4)==0
    assert t.hle("GetLastError")==1113
    assert t.hle("MultiByteToWideChar",1251,0,0,2,0x2000,4)==0
    assert t.hle("GetLastError")==87
    assert t.wide("😀",used=True)==b"?"
    assert struct.unpack("<I",t.read(0x4000,4))[0]==1
    t.write(0x4100,b"!")
    assert t.wide("😀",used=True,default=0x4100)==b"!"
    t.write(0x1000,b"\x00\xd8")
    assert t.hle("WideCharToMultiByte",65001,0x80,0x1000,1,0x2000,8,0,0)==0
    assert t.hle("GetLastError")==1113
    upper="ЁЖИК ПРИВЕТ"
    t.write(0x1000,upper.encode("utf-16le"))
    assert t.hle("LCMapStringW",0x419,0x100,0x1000,len(upper),0x2000,len(upper))==len(upper)
    assert t.read(0x2000,len(upper)*2).decode("utf-16le")==upper.lower()
    t.language("Spanish")
    assert t.hle("GetACP")==1252
    assert t.hle("GetThreadLocale")==0x409
    assert t.multi("Café €".encode("cp1252"),0)=="Café €"
    t.language("Russian")
    assert t.hle("GetACP")==1251
    print("PATCHED ARM64 PASS: Russian selection, CP1251 roundtrip/Ёё, all byte decoding, UTF8, CP1252, CP437, locale/case, errors, capacity, stdcall; bias="+hex(base),flush=True)

if __name__=="__main__":
    baseline(sys.argv[1])
    gc.collect()
    patched(sys.argv[2],0)
    gc.collect()
    patched(sys.argv[2],0x1000000000)
    print("ARM64_CODEC_VERIFIED_SHA256="+hashlib.sha256(Path(sys.argv[2]).read_bytes()).hexdigest(),flush=True)
