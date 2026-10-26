package com.nfsu2.androidevolved;

import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.Typeface;
import android.util.Log;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.BitSet;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;

/** Repairs only the fingerprinted Russian-English/HD-texture mismatch.
 * No game artwork is bundled: glyphs are rendered with the device's system font.
 * Original language strings, conversion tables, glyph metrics and kerning remain unchanged;
 * glyph atlas coordinates are repacked and matched to uniquely named DXT3 images.
 */
final class FontTextureRepair {
    static final String ENGLISH_SHA = "9cac7383781a0edb95fe585b61aaeee8504da06057e0042afd0902880337b11f";
    static final String TEXTURES_SHA = "bb25a70c5483cc12803b924bad38300d5a46eedf66855b20f2e1ac1a75b22dc1";
    private static final int MAX = 32 * 1024 * 1024;
    private static final String MARKER = ".nfsu2-font-repair-v1.properties";
    static final class Result {
        final boolean changed, supported;
        final String message;
        Result(boolean changed, boolean supported, String message) {
            this.changed=changed; this.supported=supported; this.message=message;
        }
    }
    static final class Built {
        final byte[] english, textures;
        final int fonts;
        Built(byte[] english, byte[] textures, int fonts) { this.english=english; this.textures=textures; this.fonts=fonts; }
    }
    static final class Glyph {
        int code,w,h,x,y,record;
        Glyph(int code,int w,int h,int x,int y,int record) {
            this.code=code;this.w=w;this.h=h;this.x=x;this.y=y;this.record=record;
        }
    }
    static final class Font {
        String name, texture;
        int width,height,textureReference;
        final List<Glyph> glyphs=new ArrayList<>();
    }
    static final class Box {
        final int x,y,w,h;
        Box(int x,int y,int w,int h) {this.x=x;this.y=y;this.w=w;this.h=h;}
        boolean contains(Box b) {return x<=b.x&&y<=b.y&&x+w>=b.x+b.w&&y+h>=b.y+b.h;}
        boolean overlaps(Box b) {return x<b.x+b.w&&b.x<x+w&&y<b.y+b.h&&b.y<y+h;}
        String key() {return x+","+y+","+w+","+h;}
    }
    static final class Texture {
        int hash;
        byte[] image, info;
        Texture(int hash,byte[] image,byte[] info) {this.hash=hash;this.image=image;this.info=info;}
    }
    private FontTextureRepair() {}

    static File child(File directory,String name) {
        File exact=new File(directory,name);
        if(exact.exists())return exact;
        File[] files=directory.listFiles();
        if(files!=null)for(File f:files)if(f.getName().equalsIgnoreCase(name))return f;
        return exact;
    }
    static boolean russianEnglish(File root) {
        try {
            File dir=child(root,"LANGUAGES");String current=sha(child(dir,"English.bin"));
            if(ENGLISH_SHA.equals(current))return true;
            File marker=new File(dir,MARKER);Properties state=new Properties();
            if(marker.isFile())try(FileInputStream in=new FileInputStream(marker)){state.load(in);}
            return ENGLISH_SHA.equals(state.getProperty("source.english"))&&current.equals(state.getProperty("patched.english"));
        }
        catch(Exception ignored) {return false;}
    }
    static Result prepare(File root) throws Exception {return prepare(root,ENGLISH_SHA,TEXTURES_SHA);}
    // Test seam for owned synthetic fixtures; production always uses the pinned hashes above.
    static Result prepare(File root,String expectedEnglish,String expectedTextures) throws Exception {
        File dir=child(root,"LANGUAGES"), english=child(dir,"English.bin"), textures=child(dir,"LanguageTextures.bin");
        if(!english.isFile()||!textures.isFile()||english.length()>4*1024*1024||textures.length()>MAX)
            return new Result(false,false,"No supported font-resource pair");
        File marker=new File(dir,MARKER);
        Properties state=new Properties();
        if(marker.isFile())try(FileInputStream in=new FileInputStream(marker)){state.load(in);}
        String eh=sha(english),th=sha(textures);
        if(expectedEnglish.equals(state.getProperty("source.english"))&&expectedTextures.equals(state.getProperty("source.textures"))) {
            boolean installed=eh.equals(state.getProperty("patched.english"))&&th.equals(state.getProperty("patched.textures"));
            if(installed&&"2".equals(state.getProperty("atlas.namespace")))
                return new Result(false,true,"Compatible private font resources already installed");
            if(installed) {
                // Turn a validated v1 pair into a recoverable migration before restoring originals.
                state.setProperty("phase","prepared");saveState(marker,state);
            }
            if("prepared".equals(state.getProperty("phase"))) {
                // Recover an interrupted two-file transaction only if all observed bytes are ours.
                boolean knownEnglish=eh.equals(expectedEnglish)||eh.equals(state.getProperty("patched.english"));
                boolean knownTextures=th.equals(expectedTextures)||th.equals(state.getProperty("patched.textures"));
                File eb=new File(dir,english.getName()+".before-font-repair");
                File tb=new File(dir,textures.getName()+".before-font-repair");
                if(knownEnglish&&knownTextures&&expectedEnglish.equals(sha(eb))&&expectedTextures.equals(sha(tb))) {
                    Files.copy(eb.toPath(),english.toPath(),StandardCopyOption.REPLACE_EXISTING);
                    Files.copy(tb.toPath(),textures.toPath(),StandardCopyOption.REPLACE_EXISTING);
                    eh=expectedEnglish;th=expectedTextures;
                } else throw new IOException("Interrupted font repair has unexpected file contents; backups preserved.");
            }
        }
        if(!expectedEnglish.equals(eh)||!expectedTextures.equals(th))
            return new Result(false,false,"Unknown language resources; left unchanged");
        Built built=rebuild(Files.readAllBytes(english.toPath()),Files.readAllBytes(textures.toPath()));
        File eb=backup(english,expectedEnglish),tb=backup(textures,expectedTextures);
        File ep=new File(dir,english.getName()+".font-repair-pending");
        File tp=new File(dir,textures.getName()+".font-repair-pending");
        writeSync(ep,built.english);writeSync(tp,built.textures);
        state.setProperty("source.english",expectedEnglish);state.setProperty("source.textures",expectedTextures);
        state.setProperty("patched.english",sha(built.english));state.setProperty("patched.textures",sha(built.textures));
        state.setProperty("atlas.namespace","2");
        state.setProperty("phase","prepared");saveState(marker,state);
        try {
            Files.move(tp.toPath(),textures.toPath(),StandardCopyOption.REPLACE_EXISTING);
            Files.move(ep.toPath(),english.toPath(),StandardCopyOption.REPLACE_EXISTING);
            if(!sha(english).equals(state.getProperty("patched.english"))||!sha(textures).equals(state.getProperty("patched.textures")))
                throw new IOException("Font repair write verification failed");
            state.setProperty("phase","done");saveState(marker,state);
        } catch(Exception failure) {
            Files.copy(eb.toPath(),english.toPath(),StandardCopyOption.REPLACE_EXISTING);
            Files.copy(tb.toPath(),textures.toPath(),StandardCopyOption.REPLACE_EXISTING);
            throw failure;
        } finally {ep.delete();tp.delete();}
        String message="Rebuilt "+built.fonts+" compatible font atlases; original resources backed up.";
        Log.i("NFSU2",message);
        return new Result(true,true,message);
    }
    private static File backup(File file,String expected) throws Exception {
        File backup=new File(file.getParentFile(),file.getName()+".before-font-repair");
        if(backup.exists()) {
            if(!expected.equals(sha(backup)))throw new IOException("Unexpected font backup; refusing to overwrite it.");
        } else {
            Files.copy(file.toPath(),backup.toPath());
            if(!expected.equals(sha(backup)))throw new IOException("Font backup verification failed");
        }
        return backup;
    }
    private static void saveState(File file,Properties state) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream();state.store(out,"NFSU2 compatible font repair");
        writeSync(file,out.toByteArray());
    }
    private static void writeSync(File file,byte[] bytes) throws IOException {
        try(FileOutputStream out=new FileOutputStream(file)){out.write(bytes);out.getFD().sync();}
    }
    static String sha(File file) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        try(FileInputStream in=new FileInputStream(file)) {
            byte[] buffer=new byte[65536];int n;
            while((n=in.read(buffer))!=-1)digest.update(buffer,0,n);
        }
        return hex(digest.digest());
    }
    static String sha(byte[] data) throws Exception {return hex(MessageDigest.getInstance("SHA-256").digest(data));}
    private static String hex(byte[] bytes) {
        StringBuilder out=new StringBuilder();
        for(byte b:bytes)out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
        return out.toString();
    }
    static int u16(byte[] b,int at) throws IOException {range(b,at,2);return (b[at]&255)|((b[at+1]&255)<<8);}
    static int i32(byte[] b,int at) throws IOException {
        range(b,at,4);return (b[at]&255)|((b[at+1]&255)<<8)|((b[at+2]&255)<<16)|(b[at+3]<<24);
    }
    static void put16(byte[] b,int at,int v) {b[at]=(byte)v;b[at+1]=(byte)(v>>>8);}
    static void put32(byte[] b,int at,int v) {for(int i=0;i<4;i++)b[at+i]=(byte)(v>>>(8*i));}
    private static void range(byte[] b,int at,int count) throws IOException {
        if(at<0||count<0||at>b.length-count)throw new IOException("Truncated font resource");
    }
    private static String str(byte[] b,int at,int count) {
        int end=at;while(end<at+count&&b[end]!=0)end++;
        return new String(b,at,end-at,StandardCharsets.US_ASCII);
    }
    static int hash(String name) {
        int hash=-1;
        for(byte b:name.toUpperCase(java.util.Locale.ROOT).getBytes(StandardCharsets.US_ASCII))hash=hash*33+(b&255);
        return hash;
    }
    private static int power(int value) throws IOException {
        if(value<1||value>2048)throw new IOException("Unsupported font atlas extent");
        int p=1;while(p<value)p<<=1;return p;
    }
    static List<Font> fonts(byte[] english) throws IOException {
        List<Font> fonts=new ArrayList<>();
        for(int at=0;at<english.length;) {
            int kind=i32(english,at),size=i32(english,at+4);range(english,at+8,size);
            if(kind==0x30201) {
                if(size<640)throw new IOException("Truncated FEngFont");
                Font f=new Font();f.name=str(english,at+8,256);f.texture=str(english,at+264,256);f.textureReference=at+264;
                int real=at+520,version=u16(english,real+8),count=u16(english,real+10);
                if(version!=366&&version!=414&&version!=415)throw new IOException("Unknown RealFont version "+version);
                int glyph=real+i32(english,real+20),maxX=1,maxY=1;
                if(count>2048||glyph<real)throw new IOException("Invalid glyph table");
                range(english,glyph,count*16);
                for(int i=0;i<count;i++) {
                    int p=glyph+16*i,c=u16(english,p),w=english[p+2]&255,h=english[p+3]&255,x=u16(english,p+4),y=u16(english,p+6);
                    if(p+16>at+8+size)throw new IOException("Glyph table exceeds font chunk");
                    f.glyphs.add(new Glyph(c,w,h,x,y,p));maxX=Math.max(maxX,x+w);maxY=Math.max(maxY,y+h);
                }
                int area=i32(english,real+4)-i32(english,real+28)-(version==366?96:112);
                f.width=power(maxX);
                if(area<=0||area%f.width!=0)throw new IOException("Invalid RealFont bitmap area");
                f.height=area/f.width;
                if(f.height<maxY||f.height>2048||(f.height&(f.height-1))!=0||f.width<4||f.height<4)
                    throw new IOException("Invalid RealFont bitmap dimensions");
                fonts.add(f);
            }
            at+=8+size;
        }
        if(fonts.isEmpty())throw new IOException("No language fonts");
        return fonts;
    }
    static void pack(Font font,byte[] english,BitSet allowed) throws IOException {
        List<Glyph> order=new ArrayList<>();
        for(Glyph g:font.glyphs)if(g.w>0&&g.h>0)order.add(g);
        order.sort((a,b)->{
            int c=Integer.compare(Math.max(b.w+2,b.h+2),Math.max(a.w+2,a.h+2));
            if(c==0)c=Integer.compare(b.w*b.h,a.w*a.h);
            return c!=0?c:Integer.compare(a.code,b.code);
        });
        List<Box> free=new ArrayList<>();free.add(new Box(0,0,font.width,font.height));
        for(Glyph g:order) {
            int pw=g.w+2,ph=g.h+2,bestShort=Integer.MAX_VALUE,bestLong=Integer.MAX_VALUE;
            Box best=null;
            for(Box r:free)if(pw<=r.w&&ph<=r.h) {
                int a=Math.min(r.w-pw,r.h-ph),b=Math.max(r.w-pw,r.h-ph);
                if(best==null||a<bestShort||(a==bestShort&&(b<bestLong||(b==bestLong&&(r.y<best.y||(r.y==best.y&&r.x<best.x)))))) {
                    best=r;bestShort=a;bestLong=b;
                }
            }
            if(best==null)throw new IOException("Glyphs do not fit the original atlas: "+font.name);
            Box used=new Box(best.x,best.y,pw,ph);g.x=used.x+1;g.y=used.y+1;
            put16(english,g.record+4,g.x);put16(english,g.record+6,g.y);allowed.set(g.record+4,g.record+8);
            Map<String,Box> split=new LinkedHashMap<>();
            for(Box r:free) {
                if(!r.overlaps(used)){split.put(r.key(),r);continue;}
                List<Box> pieces=new ArrayList<>();
                if(used.y>r.y)pieces.add(new Box(r.x,r.y,r.w,used.y-r.y));
                if(used.y+used.h<r.y+r.h)pieces.add(new Box(r.x,used.y+used.h,r.w,r.y+r.h-used.y-used.h));
                if(used.x>r.x)pieces.add(new Box(r.x,r.y,used.x-r.x,r.h));
                if(used.x+used.w<r.x+r.w)pieces.add(new Box(used.x+used.w,r.y,r.x+r.w-used.x-used.w,r.h));
                for(Box p:pieces)if(p.w>0&&p.h>0)split.put(p.key(),p);
            }
            List<Box> candidates=new ArrayList<>(split.values());free=new ArrayList<>();
            for(int i=0;i<candidates.size();i++) {
                Box r=candidates.get(i);boolean contained=false;
                for(int j=0;j<candidates.size();j++)if(i!=j&&candidates.get(j).contains(r)){contained=true;break;}
                if(!contained)free.add(r);
            }
        }
    }
    static byte[] render(Font f) throws IOException {
        Bitmap bitmap=Bitmap.createBitmap(f.width,f.height,Bitmap.Config.ARGB_8888);
        Canvas canvas=new Canvas(bitmap);Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
        String family=f.name.contains("arial")?"sans-serif":f.name.contains("lcd")?"monospace":"sans-serif-condensed";
        int style=f.name.contains("conduit")?Typeface.BOLD_ITALIC:f.name.contains("impact")?Typeface.BOLD:Typeface.NORMAL;
        paint.setTypeface(Typeface.create(family,style));paint.setColor(Color.WHITE);paint.setTextSize(80);
        Rect bounds=new Rect();
        for(Glyph g:f.glyphs) {
            if(g.w==0||g.h==0||g.code<32||(g.code>=127&&g.code<160))continue;
            String letter=String.valueOf((char)g.code);
            if(!paint.hasGlyph(letter)) {
                if((g.code>=0x410&&g.code<=0x44f)||g.code==0x401||g.code==0x451)throw new IOException("System font has no Cyrillic glyph U+"+Integer.toHexString(g.code));
                continue;
            }
            paint.getTextBounds(letter,0,letter.length(),bounds);
            if(bounds.isEmpty())continue;
            canvas.save();canvas.clipRect(g.x,g.y,g.x+g.w,g.y+g.h);canvas.translate(g.x,g.y);
            canvas.scale(g.w/(float)bounds.width(),g.h/(float)bounds.height());
            canvas.drawText(letter,-bounds.left,-bounds.top,paint);canvas.restore();
        }
        byte[] pixels=dxt3(bitmap);bitmap.recycle();return pixels;
    }
    static byte[] dxt3(Bitmap bitmap) {
        int width=bitmap.getWidth(),height=bitmap.getHeight();byte[] out=new byte[width*height];int at=0;
        int[] block=new int[16];
        for(int y=0;y<height;y+=4)for(int x=0;x<width;x+=4) {
            bitmap.getPixels(block,0,4,x,y,4,4);long alpha=0;
            for(int p=0;p<16;p++)alpha|=(long)(((block[p]>>>24)+8)/17)<<(4*p);
            for(int j=0;j<8;j++)out[at+j]=(byte)(alpha>>>(8*j));
            out[at+8]=(byte)255;out[at+9]=(byte)255;out[at+10]=(byte)255;out[at+11]=(byte)255;
            at+=16;
        }
        return out;
    }
    static byte[] decode(byte[] blob) throws IOException {
        if(blob.length<16||!str(blob,0,4).equals("JDLZ")||blob[4]!=2||i32(blob,12)!=blob.length)
            throw new IOException("Invalid JDLZ header");
        int size=i32(blob,8);if(size<0||size>MAX)throw new IOException("JDLZ output exceeds limit");
        byte[] out=new byte[size];int in=16,pos=0,literal=1,match=1;
        while(pos<size) {
            if(literal==1){range(blob,in,1);literal=(blob[in++]&255)|256;}
            if(match==1){range(blob,in,1);match=(blob[in++]&255)|256;}
            if((literal&1)!=0) {
                range(blob,in,2);int a=blob[in++]&255,b=blob[in++]&255,length,distance;
                if((match&1)!=0){length=(b|((a&240)<<4))+3;distance=(a&15)+1;}
                else {length=(a&31)+3;distance=(b|((a&224)<<3))+17;}
                if(distance>pos||length>size-pos)throw new IOException("Invalid JDLZ back reference");
                for(int j=0;j<length;j++){out[pos]=out[pos-distance];pos++;}
                match>>>=1;
            } else {range(blob,in,1);out[pos++]=blob[in++];}
            literal>>>=1;
        }
        return out;
    }
    static byte[] encode(byte[] raw) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream();out.write(new byte[16]);
        for(int i=0;i<raw.length;) {
            out.write(0);if(i==0)out.write(0);
            int n=Math.min(8,raw.length-i);out.write(raw,i,n);i+=n;
        }
        // The game refills its token flags before checking the packed-byte count.
        // Include that final flag even when no output bytes remain.
        if(raw.length>0&&raw.length%8==0)out.write(0);
        byte[] result=out.toByteArray();System.arraycopy("JDLZ".getBytes(StandardCharsets.US_ASCII),0,result,0,4);
        result[4]=2;result[5]=16;put32(result,8,raw.length);put32(result,12,result.length);return result;
    }
    private static byte[] find(byte[] file,int wanted,int begin,int end,int depth) throws IOException {
        if(depth>16)throw new IOException("TPK nesting too deep");
        for(int p=begin;p<end;) {
            if(end-p<8)break;
            int kind=i32(file,p),size=i32(file,p+4);range(file,p+8,size);
            if(p+8+size>end)throw new IOException("Chunk exceeds parent");
            if(kind==wanted)return Arrays.copyOfRange(file,p+8,p+8+size);
            if((kind&0x80000000)!=0) {
                byte[] found=find(file,wanted,p+8,p+8+size,depth+1);if(found!=null)return found;
            }
            p+=8+size;
        }
        return null;
    }
    private static byte[] required(byte[] file,int wanted) throws IOException {
        byte[] b=find(file,wanted,0,file.length,0);
        if(b==null)throw new IOException("Missing TPK chunk "+Integer.toHexString(wanted));return b;
    }
    static List<Texture> textures(byte[] file) throws IOException {
        byte[] table=required(file,0x33310003);
        if(table.length%24!=0||table.length/24>128)throw new IOException("Invalid compressed texture table");
        List<Texture> textures=new ArrayList<>();
        for(int p=0;p<table.length;p+=24) {
            int hash=i32(table,p),offset=i32(table,p+4),size=i32(table,p+8),length=i32(table,p+12),tail=i32(table,p+16);
            range(file,offset,size);if(tail!=256)throw new IOException("Unsupported compressed texture metadata");
            byte[] raw=decode(Arrays.copyOfRange(file,offset,offset+size));
            if(raw.length!=length||raw.length<156)throw new IOException("Invalid texture output length");
            byte[] info=Arrays.copyOfRange(raw,raw.length-156,raw.length);
            int imageSize=i32(info,56);
            if(imageSize!=raw.length-156||i32(info,60)!=0||i32(info,36)!=hash)throw new IOException("Unexpected texture layout");
            textures.add(new Texture(hash,Arrays.copyOf(raw,imageSize),info));
        }
        return textures;
    }
    static Built rebuild(byte[] originalEnglish,byte[] originalTextures) throws Exception {
        byte[] english=originalEnglish.clone();List<Font> fonts=fonts(english);List<Texture> textures=textures(originalTextures);
        Map<Integer,Texture> byHash=new LinkedHashMap<>();for(Texture t:textures)byHash.put(t.hash,t);
        textures.clear();
        if(byHash.isEmpty())throw new IOException("No texture template");
        Texture family=byHash.get(hash("conduitmditc_tt14i"));
        byte[] template=(family==null?byHash.values().iterator().next():family).info;
        BitSet allowed=new BitSet();
        int aliasIndex=0;
        for(Font f:fonts) {
            pack(f,english,allowed);Texture old=byHash.get(hash(f.texture));
            f.texture="NFSRU2_V2_"+aliasIndex++;
            int hash=hash(f.texture);
            if(byHash.containsKey(hash))throw new IOException("Private font texture hash collision");
            Arrays.fill(english,f.textureReference,f.textureReference+256,(byte)0);
            byte[] reference=f.texture.getBytes(StandardCharsets.US_ASCII);
            System.arraycopy(reference,0,english,f.textureReference,reference.length);
            allowed.set(f.textureReference,f.textureReference+256);
            byte[] info=(old==null?template:old.info).clone();byte[] image=render(f);
            Arrays.fill(info,12,36,(byte)0);byte[] name=f.texture.toUpperCase(java.util.Locale.ROOT).getBytes(StandardCharsets.US_ASCII);
            if(name.length>=24)throw new IOException("Font texture name too long");
            System.arraycopy(name,0,info,12,name.length);put32(info,36,hash);
            put32(info,56,image.length);put32(info,60,0);put32(info,64,image.length);
            put16(info,68,f.width);put16(info,70,f.height);
            info[72]=(byte)Integer.numberOfTrailingZeros(f.width);info[73]=(byte)Integer.numberOfTrailingZeros(f.height);
            info[74]=0x24;info[75]=0;put16(info,76,0);info[78]=1;
            put32(info,144,0x33545844);
            byHash.put(hash,new Texture(hash,image,info));
        }
        for(int i=0;i<english.length;i++)if(english[i]!=originalEnglish[i]&&!allowed.get(i))
            throw new IOException("Unexpected modification outside glyph coordinates and texture references");
        List<Texture> entries=new ArrayList<>(byHash.values());entries.sort((a,b)->Integer.compareUnsigned(a.hash,b.hash));
        byte[] header=required(originalTextures,0x33310001),dataInfo=required(originalTextures,0x33320001);
        if(header.length!=124||i32(header,0)!=5||dataInfo.length!=24)throw new IOException("Unsupported TPK version");
        int cursor=0;List<byte[]> streams=new ArrayList<>();
        for(Texture t:entries) {
            put32(t.info,48,cursor);put32(t.info,52,cursor+t.image.length);cursor+=t.image.length;
            streams.add(encode(join(t.image,t.info)));
        }
        byte[] hashes=new byte[entries.size()*8],table=new byte[entries.size()*24];
        int headerBodyLength=132+8+hashes.length+8+table.length;
        int afterHeader=64+8+headerBodyLength;
        byte[] between=padding(afterHeader);
        int dataStart=afterHeader+between.length;
        byte[] beforeData=padding(dataStart+8+32);
        int imageChunkStart=dataStart+8+32+beforeData.length;
        int offset=imageChunkStart+128;
        for(int i=0;i<entries.size();i++) {
            Texture t=entries.get(i);byte[] stream=streams.get(i);
            put32(hashes,i*8,t.hash);put32(table,i*24,t.hash);put32(table,i*24+4,offset);
            put32(table,i*24+8,stream.length);put32(table,i*24+12,t.image.length+156);put32(table,i*24+16,256);
            offset+=stream.length;
        }
        byte[] prefix=new byte[120];Arrays.fill(prefix,(byte)0x11);
        ByteArrayOutputStream images=new ByteArrayOutputStream();images.write(prefix);
        for(byte[] stream:streams)images.write(stream);
        byte[] head=chunk(0xb3310000,join(chunk(0x33310001,header),chunk(0x33310002,hashes),chunk(0x33310003,table)));
        byte[] data=chunk(0xb3320000,join(chunk(0x33320001,dataInfo),beforeData,chunk(0x33320002,images.toByteArray())));
        byte[] result=chunk(0xb3300000,join(chunk(0,new byte[48]),head,between,data));
        List<Texture> checked=textures(result);
        if(checked.size()!=entries.size())throw new IOException("Rebuilt TPK count mismatch");
        for(int i=0;i<checked.size();i++)
            if(checked.get(i).hash!=entries.get(i).hash||!Arrays.equals(checked.get(i).image,entries.get(i).image))
                throw new IOException("Rebuilt TPK roundtrip failed");
        return new Built(english,result,fonts.size());
    }
    private static byte[] padding(int current) {
        int next=((current+8+127)/128)*128;return chunk(0,new byte[next-current-8]);
    }
    static byte[] chunk(int id,byte[] data) {
        byte[] out=new byte[8+data.length];put32(out,0,id);put32(out,4,data.length);System.arraycopy(data,0,out,8,data.length);return out;
    }
    static byte[] join(byte[]... blocks) throws IOException {
        ByteArrayOutputStream out=new ByteArrayOutputStream();for(byte[] block:blocks)out.write(block);return out.toByteArray();
    }
}
