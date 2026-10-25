#!/usr/bin/env python3
"""Check synthetic font streams with the shipped lifted game JDLZ decoder."""
from pathlib import Path
import struct,sys
from native_codec_runner import NativeRunner
r=NativeRunner(Path(sys.argv[1]).read_bytes())
r.initialize()
r.uc.mem_map(0x100000000,0x1000000)
r.put64(r.symbols['g_mem_base']['st_value'],0x100000000)
def write(at,data):r.uc.mem_write(0x100000000+at,bytes(data))
def read(at,n):return bytes(r.uc.mem_read(0x100000000+at,n))
def reg(name,value):r.uc.mem_write(r.symbols[name]['st_value'],struct.pack('<I',value))
lookup=r.symbols['recomp_lookup']['st_value']
decoder=r.call(lookup,0x573700)
print('JDLZ_GAME_ENTRY',hex(decoder),flush=True)
assert decoder
def literal(raw):
    b=bytearray(16)
    for i in range(0,len(raw),8):
        b.append(0)
        if not i:b.append(0)
        b.extend(raw[i:i+8])
    if len(raw)%8==0:b.append(0)
    struct.pack_into('<4sBBHII',b,0,b'JDLZ',2,16,0,len(raw),len(b))
    return b
for n in (1,7,8,9,8193,65536,524288):
    raw=bytes((i*37+i//13)&255 for i in range(n));packed=literal(raw)
    write(0x10000,packed);write(0x200000,b'\xa5'*(n+32))
    write(0x900000,struct.pack('<III',0x12345678,0x10000,0x200000))
    reg('g_esp',0x900000)
    r.call(decoder,count=150000000)
    actual=read(0x200000,n)
    assert actual==raw,(n,next((i for i,(a,b) in enumerate(zip(actual,raw)) if a!=b),-1))
    assert read(0x200000+n,32)==b'\xa5'*32
    print('GAME_JDLZ_OK',n,'packed',len(packed),flush=True)
print('GAME_FONT_STREAM_CONTRACT_VERIFIED',flush=True)

# Capture the actual game's generated font quad arguments before the graphics backend.
from unicorn import UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_PC
quad=r.call(lookup,0x51bfc0)
draw=r.call(lookup,0x519fc0)
captured=[]
def capture(uc,address,size,data):
    sp=struct.unpack('<I',uc.mem_read(r.symbols['g_esp']['st_value'],4))[0]
    values=struct.unpack('<12I',read(sp+4,48))
    captured.append(values)
    uc.reg_write(UC_ARM64_REG_PC,r.STOP)
r.uc.hook_add(UC_HOOK_CODE,capture,begin=draw,end=draw)
write(0x3000,bytes(256));write(0x3008,struct.pack('<I',0x4000))
write(0x4000,bytes(256));write(0x4044,struct.pack('<HH',512,256))
write(0x2000,struct.pack('<HBBHH8B',0x41f,16,20,182,23,0,2,6,0,0,0,15,0))
write(0x5000,bytes(256))
write(0x7844f8,struct.pack('<f',1.0))
write(0x900000,struct.pack('<8I',0x12345678,0x2000,0x5000,0x42c80000,0x42c80000,0xffffffff,0,0))
reg('g_esp',0x900000);reg('g_ecx',0x3000)
r.call(quad)
assert len(captured)==1
print('GAME_FONT_QUAD_ARGS',captured[0],flush=True)
print('GAME_FONT_QUAD_FLOATS',struct.unpack('<12f',struct.pack('<12I',*captured[0])),flush=True)
