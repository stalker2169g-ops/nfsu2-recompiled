#!/usr/bin/env python3
"""Check synthetic font streams with the shipped lifted game JDLZ decoder."""
from pathlib import Path
import struct,sys
from native_codec_runner import NativeRunner
r=NativeRunner(Path(sys.argv[1]).read_bytes())
r.initialize()
r.uc.mem_map(0x100000000,0x1000000)
r.put64(r.symbols['g_mem_base']['st_value'],0x100000000)
def write(at,data):r.uc.mem_write(0x100000000+at,data)
def read(at,n):return bytes(r.uc.mem_read(0x100000000+at,n))
def reg(name,value):r.uc.mem_write(r.symbols[name]['st_value'],struct.pack('<I',value))
matches=[s for n,s in r.symbols.items() if '00573700' in n.lower()]
print('JDLZ_SYMBOLS',[(s.name,hex(s['st_value'])) for s in matches],flush=True)
assert len(matches)==1
def literal(raw):
    b=bytearray(16)
    for i in range(0,len(raw),8):
        b.append(0)
        if not i:b.append(0)
        b.extend(raw[i:i+8])
    struct.pack_into('<4sBBHII',b,0,b'JDLZ',2,16,0,len(raw),len(b))
    return b
for n in (1,7,8,9,8193,65536,524288):
    raw=bytes((i*37+i//13)&255 for i in range(n));packed=literal(raw)
    write(0x10000,packed);write(0x200000,b'\xa5'*(n+32))
    write(0x900000,struct.pack('<III',0x12345678,0x10000,0x200000))
    reg('g_esp',0x900000)
    r.call(matches[0]['st_value'],count=150000000)
    actual=read(0x200000,n)
    assert actual==raw,(n,next((i for i,(a,b) in enumerate(zip(actual,raw)) if a!=b),-1))
    assert read(0x200000+n,32)==b'\xa5'*32
    print('GAME_JDLZ_OK',n,'packed',len(packed),flush=True)
print('GAME_FONT_STREAM_CONTRACT_VERIFIED',flush=True)
