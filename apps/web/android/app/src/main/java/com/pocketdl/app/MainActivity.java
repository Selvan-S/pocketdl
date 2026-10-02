package com.pocketdl.app;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import com.chaquo.python.PyObject;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        // Get the app's external files directory for SQLite and Downloads
        String storageDir = getExternalFilesDir(null).getAbsolutePath();
        
        // Copy FFmpeg from assets so yt-dlp can execute it
        try {
            java.io.File binDir = new java.io.File(storageDir, "bin");
            if (!binDir.exists()) binDir.mkdirs();
            
            String[] bins = {"ffmpeg", "ffprobe"};
            for (String bin : bins) {
                java.io.File outFile = new java.io.File(binDir, bin);
                if (!outFile.exists()) {
                    java.io.InputStream in = getAssets().open("bin/" + bin);
                    java.io.FileOutputStream out = new java.io.FileOutputStream(outFile);
                    byte[] buffer = new byte[1024];
                    int read;
                    while ((read = in.read(buffer)) != -1) {
                        out.write(buffer, 0, read);
                    }
                    in.close();
                    out.flush();
                    out.close();
                    outFile.setExecutable(true);
                }
            }
        } catch (java.io.IOException e) {
            e.printStackTrace();
        }

        // Start the FastAPI backend
        Python py = Python.getInstance();
        PyObject androidMain = py.getModule("android_main");
        androidMain.callAttr("start_server", storageDir);
    }
}
