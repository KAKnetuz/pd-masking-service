// Load scenario for the checker profile.
// One iteration = synchronous pair "masking -> unmasking" with one payload_id.
// Scenario is selected by the SCENARIO env var: checker (default), rps1000, rps2000.
// Run:
//   k6 run load/k6_process.js
//   k6 run -e SCENARIO=smoke load/k6_process.js
//   k6 run -e SCENARIO=rps1000 load/k6_process.js
//   k6 run -e SCENARIO=rps2000 load/k6_process.js
import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Counter, Trend } from "k6/metrics";
import { textSummary } from "https://jslib.k6.io/k6-summary/0.0.2/index.js";

const BASE_URL = __ENV.BASE_URL || "http://51.250.4.227";
const SCENARIO = __ENV.SCENARIO || "checker";

// Texts are loaded from an ASCII-only JSON produced by scripts/export_load_texts.py.
const TEXTS = JSON.parse(open("./texts.json"));

// Long text: complex sample repeated until at least 20000 chars.
function buildLongText() {
  let text = "";
  while (text.length < 20000) {
    text += TEXTS.complex.text + " ";
  }
  return text;
}
const LONG_TEXT = buildLongText();

// Text selection: 60% short phrases, 35% complex sample, 5% long text.
function pickText() {
  const r = Math.random();
  if (r < 0.6) {
    return TEXTS.short[Math.floor(Math.random() * TEXTS.short.length)];
  }
  if (r < 0.95) {
    return TEXTS.complex;
  }
  return { text: LONG_TEXT, has_pd: true };
}

// Descriptions of all scenarios. Only the one selected via SCENARIO goes into options.
const ALL_SCENARIOS = {
  smoke: {
    executor: "constant-vus",
    vus: 5,
    duration: "10s",
  },
  checker: {
    executor: "ramping-vus",
    stages: [
      { duration: "30s", target: 50 },
      { duration: "60s", target: 200 },
      { duration: "120s", target: 200 },
      { duration: "30s", target: 0 },
    ],
  },
  rps1000: {
    executor: "constant-arrival-rate",
    rate: 500,
    timeUnit: "1s",
    duration: "60s",
    preAllocatedVUs: 300,
    maxVUs: 1000,
  },
  rps2000: {
    executor: "constant-arrival-rate",
    rate: 1000,
    timeUnit: "1s",
    duration: "60s",
    preAllocatedVUs: 300,
    maxVUs: 1000,
  },
};

if (!ALL_SCENARIOS[SCENARIO]) {
  throw new Error(
    `Unknown SCENARIO "${SCENARIO}". Available scenarios: ${Object.keys(ALL_SCENARIOS).join(", ")}.`,
  );
}

export const options = {
  scenarios: { [SCENARIO]: ALL_SCENARIOS[SCENARIO] },
  // 429 is not treated as an error: the checker waits for Retry-After and retries.
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  thresholds: {
    http_req_duration: ["p(95)<500"],
    http_req_failed: ["rate<0.01"],
    unmask_ok: ["rate>0.99"],
    mask_hides_pd: ["rate>0.99"],
  },
};

http.setResponseCallback(http.expectedStatuses(200, 429));

const params = { headers: { "Content-Type": "application/json" }, timeout: "10s" };

// k6 metrics.
const unmaskOk = new Rate("unmask_ok");
const maskHidesPd = new Rate("mask_hides_pd");
const http429 = new Counter("http_429");
const maskDuration = new Trend("mask_duration");
const unmaskDuration = new Trend("unmask_duration");

// POST with retry on 429: wait Retry-After (seconds, default 1), max 2 retries.
// If 429 remains, count it into http_429 and return null (iteration is aborted).
function postWithRetry(url, body) {
  let res = http.post(url, body, params);
  let attempts = 0;
  while (res.status === 429 && attempts < 2) {
    const retryAfter = Number(res.headers["Retry-After"] || 1);
    sleep(retryAfter);
    res = http.post(url, body, params);
    attempts++;
  }
  if (res.status === 429) {
    http429.add(1);
    return null;
  }
  return res;
}

export default function () {
  const item = pickText();
  const id = `${__VU}-${__ITER}-${Date.now()}`;

  // Masking.
  const masked = postWithRetry(`${BASE_URL}/process`, JSON.stringify({ payload: item.text, payload_id: id }));
  if (masked === null) return; // 429 remained after retries - no unmasking.
  if (!check(masked, { "mask 200": (r) => r.status === 200 })) return;
  maskDuration.add(masked.timings.duration);

  // For texts that contain PD, masking must change the text.
  if (item.has_pd) {
    const changed = check(masked, {
      "mask changes text with PD": (r) => r.json("result") !== item.text,
    });
    maskHidesPd.add(changed);
  }

  // Unmasking with the same payload_id and the received mask.
  const restored = postWithRetry(
    `${BASE_URL}/process`,
    JSON.stringify({ payload: masked.json("result"), payload_id: id }),
  );
  if (restored === null) return; // 429 remained after retries.
  const ok = check(restored, {
    "unmask returns original": (r) => r.status === 200 && r.json("result") === item.text,
  });
  unmaskOk.add(ok);
  unmaskDuration.add(restored.timings.duration);
}

export function handleSummary(data) {
  const scenario = __ENV.SCENARIO || "checker";
  const out = `load/results/summary-${scenario}.json`;
  return {
    stdout: textSummary(data, { indent: " ", enableColors: true }),
    [out]: JSON.stringify(data, null, 2),
  };
}