import { NextResponse, type NextRequest } from "next/server";

/**
 * Route gate (Next.js 16 "proxy" convention, formerly middleware).
 *
 * This is a UX redirect ONLY. It is deliberately NOT the security boundary.
 * It checks for the presence of a session cookie, which is cheap and keeps the
 * heavyweight Auth.js config (and its optional `pg` adapter) out of the proxy
 * runtime entirely.
 *
 * Actual enforcement happens twice, server-side, where it can't be spoofed:
 *   - app/app/page.tsx      re-reads the session and redirects if absent
 *   - app/api/ask/route.ts  verifies the session before minting any token
 * A forged cookie therefore gets you a rendered shell and nothing else.
 */
const SESSION_COOKIES = [
  "authjs.session-token",
  "__Secure-authjs.session-token",
];

export function proxy(request: NextRequest) {
  const hasSessionCookie = SESSION_COOKIES.some((name) =>
    request.cookies.has(name),
  );

  if (!hasSessionCookie) {
    const signInUrl = new URL("/signin", request.nextUrl.origin);
    signInUrl.searchParams.set("callbackUrl", request.nextUrl.pathname);
    return NextResponse.redirect(signInUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/app/:path*"],
};
