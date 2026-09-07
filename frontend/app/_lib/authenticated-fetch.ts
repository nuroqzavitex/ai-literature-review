const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";
const TOKEN_RETRIES = 12;

type TokenProvider = (options?: { skipCache?: boolean }) => Promise<string | null>;

type AuthenticatedJsonOptions = {
  signInMessage?: string;
  fallbackError?: (status: number) => string;
};

async function resolveToken(getToken: TokenProvider, refresh = false) {
  let token = await getToken(refresh ? { skipCache: true } : undefined);
  for (let attempt = 0; !token && attempt < TOKEN_RETRIES; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 150));
    token = await getToken({ skipCache: true });
  }
  return token;
}

export async function authenticatedJson<T>(
  getToken: TokenProvider,
  path: string,
  init?: RequestInit,
  options: AuthenticatedJsonOptions = {},
): Promise<T> {
  const send = (token: string | null) => {
    const headers = new Headers(init?.headers);
    if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return fetch(API + path, { ...init, headers });
  };

  let token = await resolveToken(getToken);
  if (!token) throw new Error(options.signInMessage ?? "Please sign in to continue.");

  let response = await send(token);
  if (response.status === 401) {
    token = await resolveToken(getToken, true);
    response = await send(token);
  }

  const body = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body?.detail;
    if (typeof detail === "string") throw new Error(detail);
    if (detail && typeof detail === "object") {
      throw new Error(String(detail.message ?? detail.code ?? `HTTP ${response.status}`));
    }
    throw new Error(options.fallbackError?.(response.status) ?? `HTTP ${response.status}`);
  }
  return body as T;
}
