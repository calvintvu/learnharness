import assert from "node:assert/strict";
import { test } from "node:test";
import { appFetch, appUrl } from "../lib/app-url.ts";

test("app URLs work at the root and under a prefix, without changing external URLs", () => {
	assert.equal(appUrl("/api/chats", ""), "/api/chats");
	assert.equal(appUrl("/api/chats?x=1", "/learnharness"), "/learnharness/api/chats?x=1");
	assert.equal(appUrl("/chat/id#message", "/learnharness"), "/learnharness/chat/id#message");
	assert.equal(appUrl("/learnharness/api/events", "/learnharness"), "/learnharness/api/events");
	assert.equal(appUrl("https://example.com/api", "/learnharness"), "https://example.com/api");
	assert.equal(appUrl("//example.com/api", "/learnharness"), "//example.com/api");
	assert.equal(appUrl("#message", "/learnharness"), "#message");
});

test("app fetch preserves native receiver, request options, and response streams", async () => {
	const original = globalThis.fetch;
	const controller = new AbortController();
	const options = { method: "POST", body: "payload", signal: controller.signal };
	const response = new Response("streamed response");
	const calls: unknown[][] = [];
	globalThis.fetch = async function (input, init) {
		assert.equal(this, globalThis);
		calls.push([input, init]);
		return response;
	};
	try {
		assert.equal(await appFetch("/api/chat", options), response);
		assert.deepEqual(calls[0], [appUrl("/api/chat"), options]);
		const request = new Request("https://example.com/api");
		await appFetch(request);
		assert.equal(calls[1]?.[0], request);
	} finally {
		globalThis.fetch = original;
	}
});
