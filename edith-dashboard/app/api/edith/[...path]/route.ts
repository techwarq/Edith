import { NextRequest, NextResponse } from "next/server";

const EDITH_API_URL = process.env.EDITH_API_URL;
const EDITH_API_TOKEN = process.env.EDITH_API_TOKEN;

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  if (!EDITH_API_URL || !EDITH_API_TOKEN) {
    return NextResponse.json(
      { error: "EDITH_API_URL / EDITH_API_TOKEN not set in edith-dashboard/.env.local" },
      { status: 500 }
    );
  }

  const { path } = await ctx.params;
  const search = new URLSearchParams(req.nextUrl.searchParams);
  search.set("token", EDITH_API_TOKEN);

  const upstream = `${EDITH_API_URL}/api/${path.join("/")}?${search.toString()}`;
  const res = await fetch(upstream, { cache: "no-store" });
  const body = await res.text();

  return new NextResponse(body, {
    status: res.status,
    headers: { "Content-Type": res.headers.get("Content-Type") ?? "application/json" },
  });
}
