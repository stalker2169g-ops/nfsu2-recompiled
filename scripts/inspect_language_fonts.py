#!/usr/bin/env python3
"""Read-only inventory of NFS language and FEngFont chunks.
Does not rewrite game data or claim to validate rendering.
Usage: python3 scripts/inspect_language_fonts.py LANGUAGES/Russian.bin
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

def cstring(data):
    return data.split(b"\0",1)[0].decode("ascii",errors="backslashreplace")

def chunks(data,start=0,end=None,depth=0):
    end=len(data) if end is None else end
    if depth>16:
        raise ValueError("Nested chunk depth exceeds 16")
    offset=start
    while offset<end:
        if end-offset<8:
            if any(data[offset:end]):
                raise ValueError("Truncated chunk header at "+hex(offset))
            break
        kind,size=struct.unpack_from("<II",data,offset)
        body=offset+8
        stop=body+size
        if stop>end:
            raise ValueError("Chunk "+hex(kind)+" at "+hex(offset)+" exceeds its container")
        yield kind,offset,data[body:stop],depth
        if kind&0x80000000 and size:
            yield from chunks(data,body,stop,depth+1)
        offset=stop

def inventory(path):
    data=Path(path).read_bytes()
    out={"file":Path(path).name,"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),
         "sections":[],"fonts":[],"language_tables":[]}
    for kind,offset,body,depth in chunks(data):
        out["sections"].append({"id":hex(kind),"offset":hex(offset),"bytes":len(body),"depth":depth})
        if kind==0x39000:
            item={"offset":hex(offset),"bytes":len(body)}
            if len(body)>=16:
                field0,count,table,strings=struct.unpack_from("<4I",body)
                item.update(field0=hex(field0),string_count=count,
                            table_offset=hex(table),strings_offset=hex(strings))
            out["language_tables"].append(item)
        elif kind==0x30201:
            font={"offset":hex(offset),"bytes":len(body)}
            if len(body)<0x200:
                font["error"]="FEngFont name header is truncated"
            else:
                font.update(name=cstring(body[:256]),texture=cstring(body[256:512]))
                real=body[512:]
                if len(real)<32:
                    font["error"]="RealFont header is truncated"
                else:
                    signature,size,version,count,flags,cx,cy,ascent,descent,glyph,kern,shape=struct.unpack_from("<4sIHHIbbBBIII",real)
                    font.update(signature=signature.decode("ascii",errors="backslashreplace"),
                                declared_size=size,version=version,glyph_count=count,flags=hex(flags),
                                center=[cx,cy],ascent=ascent,descent=descent,
                                glyph_table_offset=hex(glyph),kerning_offset=hex(kern),shape_offset=hex(shape),
                                glyph_table_in_chunk=glyph<len(real),kerning_in_chunk=kern<len(real),
                                external_shape=shape>=len(real))
                    if glyph<len(real):
                        font["glyph_table_prefix_hex"]=real[glyph:glyph+64].hex()
            out["fonts"].append(font)
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files",nargs="+",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    reports=[]
    for path in args.files:
        try:
            reports.append(inventory(path))
        except (OSError,ValueError,struct.error) as error:
            reports.append({"file":path.name,"error":str(error)})
    text=json.dumps(reports,ensure_ascii=False,indent=2)
    if args.output:
        args.output.write_text(text,encoding="utf-8")
    else:
        print(text)
    return int(any("error" in report for report in reports))

if __name__=="__main__":
    raise SystemExit(main())
