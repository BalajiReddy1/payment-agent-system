import { NextRequest, NextResponse } from "next/server";

const API_BASE_URL = process.env.AGENT_API_URL ?? "http://localhost:8000";

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = new URL(`/` + path.join("/"), API_BASE_URL);
  target.search = request.nextUrl.search;

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const response = await fetch(target, {
    method: request.method,
    headers: hasBody ? { "content-type": request.headers.get("content-type") ?? "application/json" } : undefined,
    body: hasBody ? await request.text() : undefined,
    cache: "no-store",
  });

  const contentType = response.headers.get("content-type") ?? "application/json";
  return new NextResponse(await response.text(), {
    status: response.status,
    headers: { "content-type": contentType, "cache-control": "no-store" },
  });
}

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return forward(request, context);
}

export async function POST(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return forward(request, context);
}

export async function DELETE(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  return forward(request, context);
}
