/** Non-Next URLs need the same build-time prefix as Next's links and router. */
const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/+$/, "");

export function appUrl(path: string, basePath = BASE_PATH): string {
	if (!path.startsWith("/") || path.startsWith("//") || !basePath) return path;
	if (path === basePath || path.startsWith(`${basePath}/`) || path.startsWith(`${basePath}?`) || path.startsWith(`${basePath}#`)) return path;
	return `${basePath}${path}`;
}

/** Preserve the native fetch receiver, request options, and streaming response. */
export const appFetch: typeof globalThis.fetch = (input, init) =>
	globalThis.fetch(typeof input === "string" ? appUrl(input) : input, init);
