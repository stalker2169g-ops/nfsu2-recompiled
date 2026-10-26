package com.nfsu2.androidevolved;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;
import org.junit.runner.RunWith;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.List;
import java.util.Properties;
import java.util.Random;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public class FontTextureRepairTest {
    private Context context() {return InstrumentationRegistry.getInstrumentation().getTargetContext();}
    private byte[] language() {
        byte[] body=new byte[512+128+3*16];
        System.arraycopy("conduitmditc_tt21i".getBytes(StandardCharsets.US_ASCII),0,body,0,18);
        System.arraycopy("conduitmditc_tt21i".getBytes(StandardCharsets.US_ASCII),0,body,256,18);
        int real=512;System.arraycopy("FNTF".getBytes(StandardCharsets.US_ASCII),0,body,real,4);
        FontTextureRepair.put32(body,real+4,128+3*16+112+4096);
        FontTextureRepair.put16(body,real+8,415);FontTextureRepair.put16(body,real+10,3);
        FontTextureRepair.put32(body,real+12,0x60009);body[real+18]=24;body[real+19]=6;
        FontTextureRepair.put32(body,real+20,128);
        FontTextureRepair.put32(body,real+24,128+3*16);
        FontTextureRepair.put32(body,real+28,128+3*16);
        int[] chars={0x410,0x41f,0x42f};
        for(int i=0;i<chars.length;i++) {
            int p=real+128+16*i;
            FontTextureRepair.put16(body,p,chars[i]);body[p+2]=16;body[p+3]=24;
            FontTextureRepair.put16(body,p+4,40);FontTextureRepair.put16(body,p+6,1);
            FontTextureRepair.put16(body,p+14,17);
        }
        byte[] strings="Owned synthetic language fixture; do not change strings".getBytes(StandardCharsets.US_ASCII);
        try {return FontTextureRepair.join(FontTextureRepair.chunk(0x39000,strings),FontTextureRepair.chunk(0x30201,body));}
        catch(IOException e){throw new AssertionError(e);}
    }
    private byte[] texturePack() throws Exception {
        byte[] header=new byte[124];FontTextureRepair.put32(header,0,5);
        byte[] info=new byte[156];byte[] name="FONT_ARIAL".getBytes(StandardCharsets.US_ASCII);
        System.arraycopy(name,0,info,12,name.length);int hash=FontTextureRepair.hash("font_arial");
        FontTextureRepair.put32(info,36,hash);FontTextureRepair.put32(info,56,1024);
        FontTextureRepair.put32(info,64,1024);FontTextureRepair.put16(info,68,32);FontTextureRepair.put16(info,70,32);
        info[72]=5;info[73]=5;info[74]=0x24;info[78]=1;info[85]=2;
        FontTextureRepair.put32(info,144,0x33545844);
        byte[] stream=FontTextureRepair.encode(FontTextureRepair.join(new byte[1024],info));
        byte[] table=new byte[24];FontTextureRepair.put32(table,0,hash);
        FontTextureRepair.put32(table,4,132+32+32);FontTextureRepair.put32(table,8,stream.length);
        FontTextureRepair.put32(table,12,1024+156);FontTextureRepair.put32(table,16,256);
        return FontTextureRepair.join(FontTextureRepair.chunk(0x33310001,header),
                FontTextureRepair.chunk(0x33310003,table),FontTextureRepair.chunk(0x33320001,new byte[24]),stream);
    }
    private File root(byte[] english,byte[] textures) throws Exception {
        File root=new File(context().getCacheDir(),"font-check-"+System.nanoTime());
        File dir=new File(root,"LANGUAGES");assertTrue(dir.mkdirs());
        Files.write(new File(dir,"English.bin").toPath(),english);
        Files.write(new File(dir,"LanguageTextures.bin").toPath(),textures);
        return root;
    }
    private Bitmap decode(FontTextureRepair.Texture t) throws Exception {
        int w=FontTextureRepair.u16(t.info,68),h=FontTextureRepair.u16(t.info,70);
        Bitmap bitmap=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);
        int[] pixels=new int[w*h];
        for(int y=0;y<h;y++)for(int x=0;x<w;x++) {
            int block=((y/4)*(w/4)+x/4)*16,p=(y%4)*4+x%4;
            int alpha=((t.image[block+p/2]&255)>>>((p&1)*4))&15;
            pixels[y*w+x]=Color.argb(alpha*17,255,255,255);
        }
        bitmap.setPixels(pixels,0,w,0,0,w,h);return bitmap;
    }
    @Test public void literalCodecIsLosslessAndBounded() throws Exception {
        for(int n:new int[]{0,1,7,8,9,1024,8193}) {
            byte[] data=new byte[n];new Random(n).nextBytes(data);
            assertArrayEquals(data,FontTextureRepair.decode(FontTextureRepair.encode(data)));
        }
        byte[] bad=FontTextureRepair.encode(new byte[8]);bad[16]=1;bad[17]=1;
        try {FontTextureRepair.decode(bad);fail("Accepted an out-of-bounds backreference");}
        catch(IOException expected) {}
    }
    @Test public void realCanvasBuildsReadableCyrillicAtMatchingCoordinates() throws Exception {
        byte[] original=language();
        FontTextureRepair.Built built=FontTextureRepair.rebuild(original,texturePack());
        assertEquals(1,built.fonts);
        int textChunkLength=8+FontTextureRepair.i32(original,4);
        assertArrayEquals(Arrays.copyOf(original,textChunkLength),Arrays.copyOf(built.english,textChunkLength));
        FontTextureRepair.Font font=FontTextureRepair.fonts(built.english).get(0);
        assertEquals(64,font.width);assertEquals(64,font.height);
        List<FontTextureRepair.Texture> textures=FontTextureRepair.textures(built.textures);
        assertEquals(2,textures.size());
        assertTrue(font.texture.startsWith("NFSRU2_V2_"));
        FontTextureRepair.Texture wanted=null;
        for(FontTextureRepair.Texture texture:textures)
            if(texture.hash==FontTextureRepair.hash(font.texture))wanted=texture;
        assertNotNull("Missing standard TT21I texture was not added",wanted);
        assertEquals(4096,wanted.image.length);
        Bitmap atlas=decode(wanted);
        for(int i=0;i<font.glyphs.size();i++) {
            FontTextureRepair.Glyph g=font.glyphs.get(i);int ink=0;
            for(int y=g.y;y<g.y+g.h;y++)for(int x=g.x;x<g.x+g.w;x++)if(Color.alpha(atlas.getPixel(x,y))>0)ink++;
            assertTrue("Empty Cyrillic glyph U+"+Integer.toHexString(g.code),ink>20);
            for(int j=0;j<i;j++) {
                FontTextureRepair.Glyph b=font.glyphs.get(j);
                assertFalse("Overlapping glyph rectangles",g.x<b.x+b.w&&b.x<g.x+g.w&&g.y<b.y+b.h&&b.y<g.y+g.h);
            }
        }
        for(int y=0;y<font.height;y++)for(int x=0;x<font.width;x++) {
            boolean inside=false;
            for(FontTextureRepair.Glyph g:font.glyphs)
                if(x>=g.x&&x<g.x+g.w&&y>=g.y&&y<g.y+g.h)inside=true;
            if(!inside)assertEquals("Ink outside declared glyph rectangles",0,Color.alpha(atlas.getPixel(x,y)));
        }
        Bitmap preview=Bitmap.createBitmap(420,110,Bitmap.Config.ARGB_8888);
        Canvas canvas=new Canvas(preview);canvas.drawColor(Color.rgb(24,24,24));
        Paint paint=new Paint(Paint.FILTER_BITMAP_FLAG);int x=12;
        for(FontTextureRepair.Glyph g:font.glyphs) {
            android.graphics.Rect src=new android.graphics.Rect(g.x,g.y,g.x+g.w,g.y+g.h);
            android.graphics.Rect dst=new android.graphics.Rect(x,15,x+g.w*3,15+g.h*3);
            canvas.drawBitmap(atlas,src,dst,paint);x+=g.w*3+18;
        }
        android.content.ContentValues values=new android.content.ContentValues();
        values.put(android.provider.MediaStore.Downloads.DISPLAY_NAME,"nfsu2-font-repair-preview.png");
        values.put(android.provider.MediaStore.Downloads.MIME_TYPE,"image/png");
        values.put(android.provider.MediaStore.Downloads.RELATIVE_PATH,"Download");
        android.net.Uri image=context().getContentResolver().insert(android.provider.MediaStore.Downloads.EXTERNAL_CONTENT_URI,values);
        assertNotNull(image);
        try(java.io.OutputStream out=context().getContentResolver().openOutputStream(image)){assertTrue(preview.compress(Bitmap.CompressFormat.PNG,100,out));}
        preview.recycle();atlas.recycle();
    }
    @Test public void backsUpBothFilesAndIsIdempotent() throws Exception {
        byte[] e=language(),t=texturePack();File root=root(e,t),dir=new File(root,"LANGUAGES");
        String eh=FontTextureRepair.sha(e),th=FontTextureRepair.sha(t);
        FontTextureRepair.Result first=FontTextureRepair.prepare(root,eh,th);
        assertTrue(first.changed);assertTrue(first.supported);
        assertArrayEquals(e,Files.readAllBytes(new File(dir,"English.bin.before-font-repair").toPath()));
        assertArrayEquals(t,Files.readAllBytes(new File(dir,"LanguageTextures.bin.before-font-repair").toPath()));
        String ep=FontTextureRepair.sha(new File(dir,"English.bin")),tp=FontTextureRepair.sha(new File(dir,"LanguageTextures.bin"));
        FontTextureRepair.Result again=FontTextureRepair.prepare(root,eh,th);
        assertFalse(again.changed);assertTrue(again.supported);
        assertEquals(ep,FontTextureRepair.sha(new File(dir,"English.bin")));
        assertEquals(tp,FontTextureRepair.sha(new File(dir,"LanguageTextures.bin")));
    }
    @Test public void recoversInterruptedTwoFileUpdate() throws Exception {
        byte[] e=language(),t=texturePack();File root=root(e,t),dir=new File(root,"LANGUAGES");
        String eh=FontTextureRepair.sha(e),th=FontTextureRepair.sha(t);
        FontTextureRepair.prepare(root,eh,th);
        File marker=new File(dir,".nfsu2-font-repair-v1.properties");Properties state=new Properties();
        try(FileInputStream in=new FileInputStream(marker)){state.load(in);}
        state.setProperty("phase","prepared");
        try(FileOutputStream out=new FileOutputStream(marker)){state.store(out,"interruption fixture");}
        Files.write(new File(dir,"English.bin").toPath(),e);
        assertTrue(FontTextureRepair.prepare(root,eh,th).changed);
        assertEquals(state.getProperty("patched.english"),FontTextureRepair.sha(new File(dir,"English.bin")));
        assertEquals(state.getProperty("patched.textures"),FontTextureRepair.sha(new File(dir,"LanguageTextures.bin")));
    }
    @Test public void unknownResourcesAreNeverModified() throws Exception {
        byte[] e=language(),t=texturePack();File root=root(e,t),dir=new File(root,"LANGUAGES");
        assertFalse(FontTextureRepair.prepare(root).supported);
        assertArrayEquals(e,Files.readAllBytes(new File(dir,"English.bin").toPath()));
        assertArrayEquals(t,Files.readAllBytes(new File(dir,"LanguageTextures.bin").toPath()));
        assertFalse(new File(dir,"English.bin.before-font-repair").exists());
    }
    @Test public void upgradesValidatedV1PairWithoutReplacingOriginalBackups() throws Exception {
        byte[] e=language(),t=texturePack();File root=root(e,t),dir=new File(root,"LANGUAGES");
        String eh=FontTextureRepair.sha(e),th=FontTextureRepair.sha(t);
        FontTextureRepair.prepare(root,eh,th);
        File marker=new File(dir,".nfsu2-font-repair-v1.properties");
        Properties state=new Properties();
        try(FileInputStream in=new FileInputStream(marker)){state.load(in);}
        state.remove("atlas.namespace");
        try(FileOutputStream out=new FileOutputStream(marker)){state.store(out,"legacy v1 marker");}
        assertTrue(FontTextureRepair.prepare(root,eh,th).changed);
        assertArrayEquals(e,Files.readAllBytes(new File(dir,"English.bin.before-font-repair").toPath()));
        assertArrayEquals(t,Files.readAllBytes(new File(dir,"LanguageTextures.bin.before-font-repair").toPath()));
        try(FileInputStream in=new FileInputStream(marker)){state.load(in);}
        assertEquals("2",state.getProperty("atlas.namespace"));
        assertFalse(FontTextureRepair.prepare(root,eh,th).changed);
    }
    @Test public void privateTextureLeavesTheOriginalSharedTextureUntouched() throws Exception {
        // Make the fixture's source texture share the font name, like a real global font pack.
        byte[] source=texturePack();int oldHash=FontTextureRepair.hash("font_arial");
        int sharedHash=FontTextureRepair.hash("conduitmditc_tt21i");
        // Rebuild a valid fixture using the existing helper's metadata and stream layout.
        int stream=132+32+32;
        byte[] raw=FontTextureRepair.decode(Arrays.copyOfRange(source,stream,source.length));
        FontTextureRepair.put32(raw,raw.length-156+36,sharedHash);
        byte[] packed=FontTextureRepair.encode(raw);
        byte[] header=Arrays.copyOf(source,stream);
        FontTextureRepair.put32(header,140,sharedHash);
        FontTextureRepair.put32(header,148,packed.length);
        byte[] original=FontTextureRepair.join(header,packed);
        FontTextureRepair.Texture before=FontTextureRepair.textures(original).get(0);
        FontTextureRepair.Built built=FontTextureRepair.rebuild(language(),original);
        FontTextureRepair.Font f=FontTextureRepair.fonts(built.english).get(0);
        assertNotEquals(sharedHash,FontTextureRepair.hash(f.texture));
        boolean found=false;
        for(FontTextureRepair.Texture after:FontTextureRepair.textures(built.textures))if(after.hash==sharedHash) {
            found=true;assertArrayEquals(before.image,after.image);
            assertEquals(32,FontTextureRepair.u16(after.info,68));
        }
        assertTrue(found);
    }
    @Test public void neverOverwritesAnUnexpectedBackup() throws Exception {
        byte[] e=language(),t=texturePack();File root=root(e,t),dir=new File(root,"LANGUAGES");
        byte[] other="do not overwrite me".getBytes(StandardCharsets.US_ASCII);
        File backup=new File(dir,"English.bin.before-font-repair");Files.write(backup.toPath(),other);
        try {FontTextureRepair.prepare(root,FontTextureRepair.sha(e),FontTextureRepair.sha(t));fail("Replaced an unrelated backup");}
        catch(IOException expected) {}
        assertArrayEquals(other,Files.readAllBytes(backup.toPath()));
        assertArrayEquals(e,Files.readAllBytes(new File(dir,"English.bin").toPath()));
        assertArrayEquals(t,Files.readAllBytes(new File(dir,"LanguageTextures.bin").toPath()));
    }
}
