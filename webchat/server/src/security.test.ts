import assert from "node:assert/strict";
import test from "node:test";
import { conversationScope } from "./security.js";

test("artifact ownership changes with browser identity and conversation", () => {
  const id = "1336549b-0113-47af-9963-d3cfe0a96100";
  assert.notEqual(conversationScope("a".repeat(64), id), conversationScope("b".repeat(64), id));
  assert.notEqual(conversationScope("a".repeat(64), id),
    conversationScope("a".repeat(64), "1336549b-0113-47af-9963-d3cfe0a96101"));
});

test("client-provided path fragments cannot become storage prefixes", () => {
  assert.throws(() => conversationScope("a".repeat(64), "../../another-user"));
});
