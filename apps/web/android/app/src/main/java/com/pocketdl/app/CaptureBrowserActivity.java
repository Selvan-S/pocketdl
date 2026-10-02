package com.pocketdl.app;

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.Button;

public class CaptureBrowserActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);

        // Simple Toolbar
        LinearLayout toolbar = new LinearLayout(this);
        toolbar.setOrientation(LinearLayout.HORIZONTAL);
        Button closeBtn = new Button(this);
        closeBtn.setText("Close");
        closeBtn.setOnClickListener(v -> finish());
        toolbar.addView(closeBtn);
        layout.addView(toolbar);

        // WebView
        WebView webView = new WebView(this);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setMediaPlaybackRequiresUserGesture(false);

        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                super.onPageFinished(view, url);
                // Inject our JS payload to intercept fetch and XMLHttpRequest
                // and send detected media manifests directly to our local FastAPI backend
                String js = "javascript:(function() {" +
                            "  const api = 'http://127.0.0.1:8787/api/captures';" +
                            "  function sendCapture(url, type) {" +
                            "    if (url.includes('.m3u8') || url.includes('.mpd')) {" +
                            "      fetch(api, {" +
                            "        method: 'POST'," +
                            "        headers: { 'Content-Type': 'application/json', 'X-PocketDL-Extension': '0.2' }," +
                            "        body: JSON.stringify({" +
                            "          url: url," +
                            "          page_url: window.location.href," +
                            "          page_title: document.title," +
                            "          request_headers: { 'User-Agent': navigator.userAgent }" +
                            "        })" +
                            "      }).catch(console.error);" +
                            "    }" +
                            "  }" +
                            "  const originalFetch = window.fetch;" +
                            "  window.fetch = async function(...args) {" +
                            "    if (typeof args[0] === 'string') sendCapture(args[0], 'fetch');" +
                            "    return originalFetch.apply(this, args);" +
                            "  };" +
                            "  const originalOpen = XMLHttpRequest.prototype.open;" +
                            "  XMLHttpRequest.prototype.open = function(method, url, ...rest) {" +
                            "    sendCapture(url, 'xhr');" +
                            "    return originalOpen.apply(this, [method, url, ...rest]);" +
                            "  };" +
                            "})();";
                view.evaluateJavascript(js, null);
            }
        });

        String url = getIntent().getStringExtra("url");
        if (url != null) {
            webView.loadUrl(url);
        }

        layout.addView(webView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, 
                LinearLayout.LayoutParams.MATCH_PARENT));

        setContentView(layout);
    }
}
