import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { filterModels, targetsForModel, capState, targetsForComparison } = require("../../static/picker-core.js");

const models = [
  { id: "a", tags: ["coding", "reasoning"] },
  { id: "b", tags: ["coding"] },
  { id: "c", tags: ["legal"] },
  { id: "d" },
];

test("filterModels with no active tags returns every model", () => {
  assert.deepEqual(filterModels(models, []).map((m) => m.id), ["a", "b", "c", "d"]);
  assert.deepEqual(filterModels(models, undefined).map((m) => m.id), ["a", "b", "c", "d"]);
});

test("filterModels uses AND semantics", () => {
  assert.deepEqual(filterModels(models, ["coding"]).map((m) => m.id), ["a", "b"]);
  assert.deepEqual(filterModels(models, ["coding", "reasoning"]).map((m) => m.id), ["a"]);
  assert.deepEqual(filterModels(models, ["coding", "legal"]), []);
});

test("filterModels hides untagged models when filtering", () => {
  assert.ok(!filterModels(models, ["coding"]).some((m) => m.id === "d"));
});

test("targetsForModel lists OpenRouter then each route", () => {
  const model = { id: "meta/x", routes: { bedrock: {}, vertex: {}, foundry: {} } };
  assert.deepEqual(targetsForModel(model), [
    { target: "meta/x", backend: "openrouter" },
    { target: "meta/x@bedrock", backend: "bedrock" },
    { target: "meta/x@vertex", backend: "vertex" },
    { target: "meta/x@foundry", backend: "foundry" },
  ]);
});

test("targetsForModel with no routes is OpenRouter only", () => {
  assert.deepEqual(targetsForModel({ id: "z/y" }), [{ target: "z/y", backend: "openrouter" }]);
});

test("capState reports cap and remaining", () => {
  assert.deepEqual(capState(0, 4), { atCap: false, remaining: 4 });
  assert.deepEqual(capState(3, 4), { atCap: false, remaining: 1 });
  assert.deepEqual(capState(4, 4), { atCap: true, remaining: 0 });
  assert.deepEqual(capState(5, 4), { atCap: true, remaining: 0 });
});

test("targetsForComparison returns the target ids in order", () => {
  const entry = {
    targets: [
      { target: "meta/x", backend: "openrouter" },
      { target: "meta/x@bedrock", backend: "bedrock" },
    ],
  };
  assert.deepEqual(targetsForComparison(entry, 4), ["meta/x", "meta/x@bedrock"]);
});

test("targetsForComparison returns nothing when the entry would exceed the cap", () => {
  const entry = { targets: [1, 2, 3, 4, 5].map((n) => ({ target: `m${n}`, backend: "openrouter" })) };
  assert.deepEqual(targetsForComparison(entry, 4), []);
});

test("targetsForComparison tolerates a malformed entry", () => {
  assert.deepEqual(targetsForComparison({}, 4), []);
  assert.deepEqual(targetsForComparison(null, 4), []);
});
