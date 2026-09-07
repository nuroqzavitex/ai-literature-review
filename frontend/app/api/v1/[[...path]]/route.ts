
import { NextResponse } from "next/server";

const DEFAULT_BACKEND_API_BASE_URL = "http://127.0.0.1:8000/api/v1";

function getBackendApiBaseUrl() {
  return (process.env.BACKEND_API_BASE_URL || DEFAULT_BACKEND_API_BASE_URL).replace(/\/+$/, "");
}

function buildTargetUrl(request: Request, pathSegments: string[] | undefined) {
  const incomingUrl = new URL(request.url);
  const backendBase = new URL(getBackendApiBaseUrl());
  const basePath = backendBase.pathname.replace(/\/+$/, "");
  const apiPath = pathSegments?.length ? `/${pathSegments.join("/")}` : "";
  const target = new URL(`${backendBase.origin}${basePath}${apiPath}`);
  target.search = incomingUrl.search;
  return target;
}

async function proxy(request: Request, pathSegments?: string[]) {
  const target = buildTargetUrl(request, pathSegments);
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("content-length");
  headers.set("x-forwarded-host", new URL(request.url).host);
  headers.set("x-forwarded-proto", new URL(request.url).protocol.replace(":", ""));

  const hasBody = !["GET", "HEAD"].includes(request.method);

  try {
    const upstreamResponse = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      redirect: "manual",
    });

    const responseHeaders = new Headers(upstreamResponse.headers);
    return new NextResponse(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders,
    });
  } catch {
    return NextResponse.json(
      {
        detail: `Không thể kết nối backend tại ${getBackendApiBaseUrl()}. Hãy kiểm tra backend rồi thử lại.`,
      },
      { status: 502, statusText: "Bad Gateway", headers: { "cache-control": "no-store" } },
    );
  }
}

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET(request: Request, context: { params: Promise<{ path?: string[] }> }) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function POST(request: Request, context: { params: Promise<{ path?: string[] }> }) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function PUT(request: Request, context: { params: Promise<{ path?: string[] }> }) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function PATCH(request: Request, context: { params: Promise<{ path?: string[] }> }) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function DELETE(request: Request, context: { params: Promise<{ path?: string[] }> }) {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function OPTIONS(request: Request, context: { params: Promise<{ path?: string[] }> }) {
  const { path } = await context.params;
  return proxy(request, path);
}
