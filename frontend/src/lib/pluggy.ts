const PLUGGY_CONNECT_SDK_URL = "https://cdn.pluggy.ai/pluggy-connect/latest/pluggy-connect.js";

declare global {
  interface Window {
    PluggyConnect?: new (options: Record<string, unknown>) => { init: () => void };
  }
}

function waitForPluggyConnectSdk(timeoutMs = 10000): Promise<void> {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const poll = () => {
      if (window.PluggyConnect) {
        resolve();
        return;
      }
      if (Date.now() - start > timeoutMs) {
        reject(new Error("Timeout aguardando window.PluggyConnect."));
        return;
      }
      window.setTimeout(poll, 100);
    };
    poll();
  });
}

export async function ensurePluggyConnectSdkLoaded(): Promise<void> {
  if (window.PluggyConnect) return;

  const existingScript = document.querySelector(
    'script[data-pluggy-connect-sdk], script[src*="pluggy-connect"]',
  );
  if (existingScript) {
    await waitForPluggyConnectSdk();
    return;
  }

  const script = document.createElement("script");
  script.src = PLUGGY_CONNECT_SDK_URL;
  script.async = true;
  script.dataset.pluggyConnectSdk = "true";

  const loadPromise = new Promise<void>((resolve, reject) => {
    script.onload = () => {
      if (window.PluggyConnect) resolve();
      else reject(new Error("SDK Pluggy Connect carregou, mas window.PluggyConnect não ficou disponível."));
    };
    script.onerror = () => {
      reject(
        new Error(
          "Não foi possível carregar o Pluggy Connect. Verifique conexão, bloqueador ou CSP.",
        ),
      );
    };
  });

  document.head.appendChild(script);
  await loadPromise;
}

export function extractPluggyItemId(data: any): string | null {
  return data?.itemId || data?.item?.id || data?.id || null;
}
