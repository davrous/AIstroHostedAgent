import assert from "node:assert/strict";
import test from "node:test";
import { events } from "./stream";

function bytes(parts: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) { parts.forEach(part => controller.enqueue(part)); controller.close(); },
  });
}

test("SSE survives UTF-8 and CRLF split across arbitrary network chunks", async () => {
  const source = new TextEncoder().encode(
    'data: {"type":"response.output_text.delta","delta":"Gémeaux"}\r\n\r\n'
    + 'data: {"type":"response.completed","response":{"id":"resp_1"}}\r\n\r\n',
  );
  const parts = Array.from(source, (_, index) => source.slice(index, index + 1));
  const result = [];
  for await (const event of events(bytes(parts))) result.push(event);
  assert.equal(result[0].delta, "Gémeaux");
  assert.equal(result[1].type, "response.completed");
});

test("SSE does not report success when the connection ends mid-response", async () => {
  const source = new TextEncoder().encode(
    'data: {"type":"response.output_text.delta","delta":"En cours"}\n\n',
  );
  await assert.rejects(async () => {
    for await (const _event of events(bytes([source]))) { /* Consume the incomplete turn. */ }
  }, /avant la fin/);
});
