import { afterEach, describe, expect, it, vi } from "vitest";

import { CSRF_HEADER, rawJson, requestHeaders } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

afterEach(() => vi.unstubAllGlobals());

describe("same-origin request headers", () => {
  it("sends the CSRF header on mutations only", () => {
    expect(CSRF_HEADER).toBe("x-dq-csrf");
    expect(requestHeaders("POST", true)).toEqual({ "content-type": "application/json", [CSRF_HEADER]: "1" });
    expect(requestHeaders("DELETE", false)).toEqual({ [CSRF_HEADER]: "1" });
    expect(requestHeaders("GET", false)).toEqual({});
    expect(requestHeaders("HEAD", false)).toEqual({});
  });
});

describe("rawJson", () => {
  it("sends JSON with credentials and the CSRF header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(rawJson("POST", "/api/v1/auth/signup", { a: 1 })).resolves.toEqual({ ok: true });
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>)[CSRF_HEADER]).toBe("1");
    expect(init.body).toBe('{"a":1}');
  });
  it("turns the error envelope into an ApiError", async () => {
    const body = { error: { code: "slug_taken", message: "A problem with the slug 'sum' exists" } };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 409 })));
    await expect(rawJson("POST", "/x", {})).rejects.toMatchObject({ status: 409, code: "slug_taken" });
  });
  it("reports a network failure as status 0", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await rawJson("GET", "/x").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).isNetwork).toBe(true);
  });
  it("does not set a JSON content type on file uploads", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    const form = new FormData();
    form.append("file", new Blob(["zip"]), "p.zip");
    await rawJson("POST", "/api/v1/problems/import", form);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>)["content-type"]).toBeUndefined();
    expect(init.body).toBe(form);
  });
});
