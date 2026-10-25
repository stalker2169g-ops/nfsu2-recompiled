/* ARM64 HLE codec replacement for the pinned v0.14.10 runtime.
 * Freestanding: no Android/libc++ ABI calls except the original error/LCMap HLE.
 * All guest addresses remain uint32_t offsets into g_mem_base.
 */
#include <stdint.h>
#include <stddef.h>
#include "cp_tables.h"
extern uint32_t g_eax, g_esp;
extern uintptr_t g_mem_base, runtime_memory;
extern unsigned char guest_language[24];
extern void original_set_error(void), original_map_string(void);
static unsigned char *p(uint32_t a) { return (unsigned char *)(g_mem_base + a); }
static uint32_t rd(uint32_t a) {
    unsigned char *b=p(a);return b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;
}
static void wr(uint32_t a,uint32_t v) {for(unsigned i=0;i<4;i++)p(a)[i]=(unsigned char)(v>>(8*i));}
static uint32_t arg(unsigned i) {return rd(g_esp+4+4*i);}
static void result(uint32_t v,unsigned n) {g_eax=v;g_esp+=4+4*n;}
static int equal(const char *a,const char *b) {if(!a)return 0;while(*a&&*a==*b){a++;b++;}return *a==*b;}
static int russian(void) {
    return guest_language[0]==14&&equal((const char*)guest_language+1,"Russian");
}
static uint32_t acp(void) {return russian()?1251:1252;}
static uint32_t effective(uint32_t cp) {return cp==0||cp==3?acp():cp==1?437:cp;}
static int valid(uint32_t cp) {return cp==1251||cp==1252||cp==437||cp==65001;}
static void failure(uint32_t error,unsigned n) {
    uint32_t sp=g_esp,old=rd(sp+4);
    wr(sp+4,error);original_set_error();wr(sp+4,old);g_esp=sp;result(0,n);
}
static uint32_t decode(uint32_t cp,unsigned char b) {
    return cp==1251?table_1251[b]:cp==1252?table_1252[b]:table_437[b];
}
static int encode(uint32_t cp,uint32_t ch) {
    for(unsigned i=0;i<256;i++)if(decode(cp,(unsigned char)i)==ch)return (int)i;
    return -1;
}
void ru_set_language(const char *language) {
    /* Called by GameActivity before guest startup, as required by the original API.
       The pinned libc++ short-string representation is checked in ARM64 tests. */
    if(runtime_memory)return;
    const char *chosen="Spanish";
    /* No absolute pointer tables: injected code must survive ASLR. */
#define CHOOSE(s) if(equal(language,s))chosen=s
    CHOOSE("Russian"); CHOOSE("Spanish"); CHOOSE("English UK"); CHOOSE("French");
    CHOOSE("German"); CHOOSE("Italian"); CHOOSE("Dutch"); CHOOSE("Swedish");
    CHOOSE("Danish"); CHOOSE("Japanese"); CHOOSE("Korean");
    CHOOSE("Chinese (Traditional)"); CHOOSE("Thai");
#undef CHOOSE
    unsigned n=0;while(chosen[n])n++;
    for(unsigned i=0;i<24;i++)guest_language[i]=0;
    guest_language[0]=(unsigned char)(n*2);
    for(unsigned i=0;i<n;i++)guest_language[i+1]=(unsigned char)chosen[i];
}
void ru_get_acp(void) {result(acp(),0);}
void ru_thread_locale(void) {result(russian()?0x419:0x409,0);}
void ru_cp_info(void) {
    uint32_t cp=effective(arg(0)),out=arg(1);
    if(!valid(cp)||!out){failure(87,2);return;}
    for(unsigned i=0;i<20;i++)p(out)[i]=0;
    wr(out,cp==65001?4:1);p(out)[4]='?';result(1,2);
}
void ru_map_string(void) {
    uint32_t sp=g_esp,locale=arg(0),flags=arg(1);
    if((locale!=0&&locale!=0x409&&locale!=0x419&&locale!=0x400&&locale!=0x800&&locale!=0x7f)||
       (flags!=0x100&&flags!=0x200)){failure(87,6);return;}
    if(locale==0x419)wr(sp+4,0x409);
    original_map_string();
    if(locale==0x419)wr(sp+4,locale);
}
static int length(uint32_t src,int32_t count,unsigned width,uint32_t *n) {
    if(!src||count==0||count< -1)return 0;
    if(count==-1) {
        *n=0;
        do {
            if(*n>=0x1000000||((uint64_t)src+((uint64_t)*n+1)*width)>0x100000000ULL)return 0;
            unsigned v=p(src+*n*width)[0];
            if(width==2)v|=(unsigned)p(src+*n*width)[1]<<8;
            (*n)++;
            if(!v)break;
        }while(1);
    }else {
        *n=(uint32_t)count;
        if(*n>0x1000000||((uint64_t)src+(uint64_t)*n*width)>0x100000000ULL)return 0;
    }
    return 1;
}
void ru_multi_to_wide(void) {
    uint32_t cp=effective(arg(0)),flags=arg(1),src=arg(2),out=arg(4),n;
    int32_t capacity=(int32_t)arg(5);
    if(!valid(cp)||capacity<0||(capacity&&!out)||!length(src,(int32_t)arg(3),1,&n)){
        failure(87,6);return;
    }
    uint32_t needed=0;
    for(unsigned pass=0;pass<2;pass++) {
        uint32_t written=0;
        for(uint32_t i=0;i<n;) {
            uint32_t ch=p(src)[i++];
            if(cp!=65001)ch=decode(cp,(unsigned char)ch);
            else if(ch>=128) {
                uint32_t start=i,k=ch>=0xf0&&ch<=0xf4?3:ch>=0xe0&&ch<=0xef?2:ch>=0xc2&&ch<=0xdf?1:0;
                uint32_t minimum=k==1?0x80:k==2?0x800:0x10000;
                int invalid=!k||n-i<k;
                ch&=k==1?31:k==2?15:7;
                if(!invalid)for(uint32_t j=0;j<k;j++){
                    unsigned b=p(src)[i++];if((b&0xc0)!=0x80){invalid=1;break;}ch=(ch<<6)|(b&63);
                }
                invalid|=ch<minimum||ch>0x10ffff||(ch>=0xd800&&ch<=0xdfff);
                if(invalid){if(flags&8){failure(1113,6);return;}ch=0xfffd;i=start;}
            }
            uint16_t units[2];unsigned count=1;
            if(ch>0xffff){ch-=0x10000;units[0]=(uint16_t)(0xd800|(ch>>10));units[1]=(uint16_t)(0xdc00|(ch&1023));count=2;}
            else units[0]=(uint16_t)ch;
            for(unsigned j=0;j<count;j++){
                if(pass){p(out+written*2)[0]=(unsigned char)units[j];p(out+written*2)[1]=(unsigned char)(units[j]>>8);}
                written++;
            }
        }
        if(!pass){
            needed=written;
            if(!capacity){result(needed,6);return;}
            if((uint32_t)capacity<needed){failure(122,6);return;}
            if((uint64_t)out+2ULL*needed>0x100000000ULL){failure(87,6);return;}
        }
    }
    result(needed,6);
}
void ru_wide_to_multi(void) {
    uint32_t cp=effective(arg(0)),flags=arg(1),src=arg(2),out=arg(4),n;
    int32_t capacity=(int32_t)arg(5);
    uint32_t default_address=arg(6),used_address=arg(7);
    if(!valid(cp)||capacity<0||(capacity&&!out)||!length(src,(int32_t)arg(3),2,&n)||
       (cp==65001&&(default_address||used_address))){failure(87,8);return;}
    unsigned char fallback=default_address?p(default_address)[0]:'?';
    uint32_t needed=0,used=0;
    for(unsigned pass=0;pass<2;pass++){
        uint32_t written=0;
        for(uint32_t i=0;i<n;i++){
            uint32_t ch=p(src+i*2)[0]|(uint32_t)p(src+i*2)[1]<<8;
            if(ch>=0xd800&&ch<=0xdbff&&i+1<n){
                uint32_t next=p(src+(i+1)*2)[0]|(uint32_t)p(src+(i+1)*2)[1]<<8;
                if(next>=0xdc00&&next<=0xdfff){ch=0x10000+((ch-0xd800)<<10)+(next-0xdc00);i++;}
            }
            if(ch>=0xd800&&ch<=0xdfff){if(flags&0x80){failure(1113,8);return;}ch=0xfffd;}
            unsigned char bytes[4];unsigned count=1;
            if(cp!=65001){int b=encode(cp,ch);bytes[0]=b<0?fallback:(unsigned char)b;used|=b<0;}
            else if(ch<0x80)bytes[0]=(unsigned char)ch;
            else if(ch<0x800){count=2;bytes[0]=(unsigned char)(0xc0|(ch>>6));bytes[1]=(unsigned char)(0x80|(ch&63));}
            else if(ch<0x10000){count=3;bytes[0]=(unsigned char)(0xe0|(ch>>12));bytes[1]=(unsigned char)(0x80|((ch>>6)&63));bytes[2]=(unsigned char)(0x80|(ch&63));}
            else {count=4;bytes[0]=(unsigned char)(0xf0|(ch>>18));bytes[1]=(unsigned char)(0x80|((ch>>12)&63));bytes[2]=(unsigned char)(0x80|((ch>>6)&63));bytes[3]=(unsigned char)(0x80|(ch&63));}
            for(unsigned j=0;j<count;j++){if(pass)p(out)[written]=bytes[j];written++;}
        }
        if(!pass){
            needed=written;
            if(used_address)wr(used_address,used);
            if(!capacity){result(needed,8);return;}
            if((uint32_t)capacity<needed){failure(122,8);return;}
            if((uint64_t)out+needed>0x100000000ULL){failure(87,8);return;}
        }
    }
    result(needed,8);
}

/* Bounded device diagnostics: observe the real font inputs without changing them. */
extern uint32_t g_ecx;
extern uint32_t font_trace_state[128];
extern int font_log(int priority,const char *tag,const char *format,...);
extern void original_font_quad(void);
static unsigned font_u16(uint32_t a) {return p(a)[0]|(unsigned)p(a)[1]<<8;}
void ru_font_quad(void) {
    uint32_t font=g_ecx,glyph=arg(0);
    if(font&&glyph) {
        uint32_t texture=rd(font+8),real=rd(font+12);
        if(texture) {
            uint32_t hash=rd(texture+36),slot=0;
            while(slot<16&&font_trace_state[slot*4]&&font_trace_state[slot*4]!=hash)slot++;
            unsigned code=font_u16(glyph);
            unsigned group=(code>=0x400&&code<=0x4ff)?2:3;
            if(slot<16&&font_trace_state[slot*4+group]<4) {
                font_trace_state[slot*4]=hash;
                unsigned sample=font_trace_state[slot*4+1]++;
                font_trace_state[slot*4+group]++;
                font_log(4,"NFSU2","FONT_TRACE sample=%u char=%04x font=%08x real=%08x glyph=%08x texture=%08x hash=%08x name=%.*s dims=%ux%u xy=%u,%u size=%ux%u",
                    sample,font_u16(glyph),font,real,glyph,texture,hash,24,(char*)p(texture+12),
                    font_u16(texture+68),font_u16(texture+70),font_u16(glyph+4),font_u16(glyph+6),p(glyph)[2],p(glyph)[3]);
            }
        }
    }
    original_font_quad();
}
