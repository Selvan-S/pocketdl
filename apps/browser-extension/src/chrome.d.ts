declare namespace chrome {
  namespace storage {
    namespace local {
      function get<T extends Record<string, unknown>>(keys: T): Promise<T>;
      function set(items: Record<string, unknown>): Promise<void>;
    }
  }

  namespace tabs {
    interface Tab { id?: number; url?: string; title?: string; }
    function get(tabId: number): Promise<Tab>;
    function create(options: { url: string }): Promise<Tab>;
    interface RemovedEvent { addListener(callback: (tabId: number) => void): void; }
    const onRemoved: RemovedEvent;
  }

  namespace webRequest {
    interface HttpHeader { name: string; value?: string; }
    interface OnBeforeSendHeadersDetails { requestId: string; tabId: number; url: string; requestHeaders?: HttpHeader[]; }
    interface OnBeforeRequestDetails { requestId: string; tabId: number; url: string; type?: string; }
    interface OnHeadersReceivedDetails { requestId: string; tabId: number; url: string; statusCode: number; responseHeaders?: HttpHeader[]; }
    interface OnCompletedDetails { requestId: string; tabId: number; url: string; statusCode: number; }
    interface OnErrorOccurredDetails { requestId: string; tabId: number; url: string; error: string; }
    interface Event<T> { addListener(callback: (details: T) => void, filter: { urls: string[]; types?: string[] }, extraInfoSpec?: string[]): void; }
    const onBeforeRequest: Event<OnBeforeRequestDetails>;
    const onBeforeSendHeaders: Event<OnBeforeSendHeadersDetails>;
    const onHeadersReceived: Event<OnHeadersReceivedDetails>;
    const onCompleted: Event<OnCompletedDetails>;
    const onErrorOccurred: Event<OnErrorOccurredDetails>;
  }
}
