import { NextResponse, type NextRequest } from "next/server";

const prod = process.env.NODE_ENV === "production";

/**
 * Next inlines its bootstrap scripts and styles, so those need 'unsafe-inline'; the dev
 * server also needs 'unsafe-eval' for fast refresh. Everything loads from and connects
 * to this origin.
 */
export function contentSecurityPolicy(isProd = prod): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'unsafe-inline'${isProd ? "" : " 'unsafe-eval'"}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    ["connect-src 'self'", ...(isProd ? [] : ["ws:"])].join(" "),
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");
}

/** Every page needs a signed-in person, except signing in and the first-run setup. */
const PUBLIC = ["/login", "/signup"];

export function needsSignIn(pathname: string): boolean {
  return !PUBLIC.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

/**
 * Sets the Content-Security-Policy on every page, and sends signed-out visitors of a
 * protected page straight to /login instead of flashing it. The cookie is only checked
 * for presence here; the API validates it on every call and the client redirects on 401.
 */
export function middleware(req: NextRequest) {
  const hasSession = req.cookies.has("dq_session");
  const { pathname, search } = req.nextUrl;
  let res: NextResponse;
  if (!hasSession && needsSignIn(pathname)) {
    const url = req.nextUrl.clone();
    url.pathname = "/login";
    url.search = "";
    url.searchParams.set("next", `${pathname}${search}`);
    res = NextResponse.redirect(url);
  } else {
    res = NextResponse.next();
  }
  res.headers.set("Content-Security-Policy", contentSecurityPolicy());
  return res;
}

export const config = {
  // Everything except the proxied API surfaces, Next internals and static files.
  matcher: ["/((?!api/|healthz|readyz|docs|openapi\\.json|_next/|favicon|icon|.*\\.(?:svg|png|jpg|ico|webp|txt|woff2?)$).*)"],
};
