import io, struct, zipfile
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
data=zipfile.ZipFile('upstream.apk').read('lib/arm64-v8a/libnfsu2_android.so')
elf=ELFFile(io.BytesIO(data)); md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
def off(va):
    for seg in elf.iter_segments():
        if seg['p_type']=='PT_LOAD' and seg['p_vaddr']<=va<seg['p_vaddr']+seg['p_filesz']:
            return seg['p_offset']+va-seg['p_vaddr']
    raise ValueError(hex(va))
relocs={}
for sec in elf.iter_sections():
    if sec['sh_type']=='SHT_RELA':
        for rel in sec.iter_relocations():
            if rel['r_info_type']==1027:
                relocs[rel['r_offset']]=rel['r_addend']
syms={s.name:s for s in elf.get_section_by_name('.dynsym').iter_symbols()}
for name in ('g_eax','g_esp','g_mem_base','g_fs_base'):
    print('GLOBAL',name,hex(syms[name]['st_value']))
for name in ('GetACP','GetThreadLocale','GetCPInfo','MultiByteToWideChar','WideCharToMultiByte','SetLastError','LCMapStringW'):
    needle=name.encode()+b'\0'; locations=[]; index=0
    while True:
        at=data.find(needle,index)
        if at<0:break
        index=at+1
        for seg in elf.iter_segments():
            if seg['p_type']=='PT_LOAD' and seg['p_offset']<=at<seg['p_offset']+seg['p_filesz']:
                locations.append(seg['p_vaddr']+at-seg['p_offset']);break
    for ptr,target in relocs.items():
        if target in locations and ptr+8 in relocs:
            fn=relocs[ptr+8];print('IMPORT',name,hex(ptr),hex(fn))
            for ins in md.disasm(data[off(fn):off(fn)+48],fn):print(hex(ins.address),ins.mnemonic,ins.op_str)
for name,sym in syms.items():
    if 'setGuestLanguage' in name:
        va=sym['st_value'];print('LANGUAGE',hex(va),sym['st_size'])
        for ins in md.disasm(data[off(va):off(va)+sym['st_size']],va):
            print(hex(ins.address),ins.mnemonic,ins.op_str)
