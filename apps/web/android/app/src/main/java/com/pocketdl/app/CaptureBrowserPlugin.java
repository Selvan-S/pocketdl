package com.pocketdl.app;

import android.content.Intent;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "CaptureBrowser")
public class CaptureBrowserPlugin extends Plugin {

    @PluginMethod
    public void open(PluginCall call) {
        String url = call.getString("url", "https://google.com");
        
        Intent intent = new Intent(getContext(), CaptureBrowserActivity.class);
        intent.putExtra("url", url);
        getContext().startActivity(intent);
        
        call.resolve();
    }
}
