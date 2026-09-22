// РќР°РіСЂСѓР·РѕС‡РЅС‹Р№ СЃС†РµРЅР°СЂРёР№ РїРѕРґ РїСЂРѕС„РёР»СЊ РїСЂРѕРІРµСЂСЏСЋС‰РµР№ СЃРёСЃС‚РµРјС‹.
// РћРґРЅР° РёС‚РµСЂР°С†РёСЏ = СЃРёРЅС…СЂРѕРЅРЅР°СЏ РїР°СЂР° В«РјР°СЃРєРёСЂРѕРІР°РЅРёРµ в†’ РґРµРјР°СЃРєРёСЂРѕРІР°РЅРёРµВ» СЃ РѕРґРЅРёРј payload_id.
// РЎС†РµРЅР°СЂРёР№ РІС‹Р±РёСЂР°РµС‚СЃСЏ РїРµСЂРµРјРµРЅРЅРѕР№ РѕРєСЂСѓР¶РµРЅРёСЏ SCENARIO: checker (РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ), rps1000, rps2000.
// Р—Р°РїСѓСЃРє:
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

// РљРѕСЂРѕС‚РєРёРµ С„СЂР°Р·С‹ СЃ РѕРґРЅРёРј С‚РёРїРѕРј РџР” (РїСЂРёРјРµСЂС‹ 1, 4, 9, 10, 16, 18, 19, 20, 22, 23, 26, 27, 28
// РёР· tests/fixtures/span_reference.yaml). РџСЂРёРјРµСЂС‹ 27 Рё 28 вЂ” В«Р»РѕРІСѓС€РєРёВ» Р±РµР· РџР”.
const SHORT_SAMPLES = [
  "РљР»РёРµРЅС‚ РРІР°РЅРѕРІ РРІР°РЅ РРІР°РЅРѕРІРёС‡ РѕР±СЂР°С‚РёР»СЃСЏ РІ Р±Р°РЅРє.",
  "Р”Р°С‚Р° СЂРѕР¶РґРµРЅРёСЏ: 12.03.1990.",
  "РџР°СЃРїРѕСЂС‚ 4509 123456.",
  "РџР°СЃРїРѕСЂС‚ СЃРµСЂРёСЏ 4510 РЅРѕРјРµСЂ 654321.",
  "Р’РѕРґРёС‚РµР»СЊСЃРєРѕРµ СѓРґРѕСЃС‚РѕРІРµСЂРµРЅРёРµ 77 РђР’ 123456.",
  "РџСЂРѕР¶РёРІР°РµС‚ РїРѕ Р°РґСЂРµСЃСѓ: 350000, Р РѕСЃСЃРёСЏ, Рі. РљСЂР°СЃРЅРѕРґР°СЂ, СѓР». РљСЂР°СЃРЅР°СЏ, Рґ. 10, РєРІ. 5.",
  "РџРёС€РёС‚Рµ РЅР° ivan.petrov@mail.ru.",
  "РўРµР»РµС„РѕРЅ +7 (916) 123-45-67.",
  "РРќРќ 500100732259.",
  "РќРѕРјРµСЂ РєР°СЂС‚С‹ 2200 1234 5678 9019.",
  "РљР°СЂС‚Р° 2200 1234 5678 9019, РґРµСЂР¶Р°С‚РµР»СЊ IVAN IVANOV, CVV 123, РїРёРЅ-РєРѕРґ 4321.",
  "РђР»РµРєСЃР°РЅРґСЂ РџСѓС€РєРёРЅ РЅР°РїРёСЃР°Р» В«Р•РІРіРµРЅРёСЏ РћРЅРµРіРёРЅР°В».",
  "РћС‚РґРµР»РµРЅРёРµ Р±Р°РЅРєР° РЅР°С…РѕРґРёС‚СЃСЏ РїРѕ Р°РґСЂРµСЃСѓ: Рі. РњРѕСЃРєРІР°, СѓР». РљР°Р»Р°РЅС‡РµРІСЃРєР°СЏ, Рґ. 27.",
];

// РЎР»РѕР¶РЅРѕРµ РїСЂРµРґР»РѕР¶РµРЅРёРµ (РїСЂРёРјРµСЂ 30 РёР· span_reference.yaml).
const COMPLEX_SAMPLE =
  "РљР»РёРµРЅС‚ РЎРёРґРѕСЂРѕРІ РџС‘С‚СЂ РђР»РµРєСЃРµРµРІРёС‡, 05.11.1985 Рі.СЂ., РїР°СЃРїРѕСЂС‚ СЃРµСЂРёСЏ 4511 РЅРѕРјРµСЂ 987654 РІС‹РґР°РЅ РћРЈР¤РњРЎ Р РѕСЃСЃРёРё РїРѕ Рі. РљСЂР°СЃРЅРѕРґР°СЂСѓ 20.01.2010, РєРѕРґ РїРѕРґСЂР°Р·РґРµР»РµРЅРёСЏ 230-001, РїСЂРѕР¶РёРІР°РµС‚: Рі. РљСЂР°СЃРЅРѕРґР°СЂ, СѓР». РЎРµРІРµСЂРЅР°СЏ, Рґ. 5, РєРІ. 12, С‚РµР». +7 918 555-44-33, email sidorov@yandex.ru, РРќРќ 500100732259, РїСЂРѕСЃРёС‚ РїРµСЂРµРІС‹РїСѓСЃС‚РёС‚СЊ РєР°СЂС‚Сѓ 2200 1234 5678 9019.";

// Р”Р»РёРЅРЅС‹Р№ С‚РµРєСЃС‚ ~20 000 СЃРёРјРІРѕР»РѕРІ: СЃР»РѕР¶РЅРѕРµ РїСЂРµРґР»РѕР¶РµРЅРёРµ, РїРѕРІС‚РѕСЂС‘РЅРЅРѕРµ РЅСѓР¶РЅРѕРµ С‡РёСЃР»Рѕ СЂР°Р·.
let LONG_TEXT = "";
while (LONG_TEXT.length < 20000) {
  LONG_TEXT += COMPLEX_SAMPLE + " ";
}

// Р’С‹Р±РѕСЂ С‚РµРєСЃС‚Р°: 60% вЂ” РєРѕСЂРѕС‚РєРёРµ С„СЂР°Р·С‹, 35% вЂ” СЃР»РѕР¶РЅРѕРµ РїСЂРµРґР»РѕР¶РµРЅРёРµ, 5% вЂ” РґР»РёРЅРЅС‹Р№ С‚РµРєСЃС‚.
function pickText() {
  const r = Math.random();
  if (r < 0.6) {
    return SHORT_SAMPLES[Math.floor(Math.random() * SHORT_SAMPLES.length)];
  }
  if (r < 0.95) {
    return COMPLEX_SAMPLE;
  }
  return LONG_TEXT;
}

// РћРїРёСЃР°РЅРёСЏ РІСЃРµС… СЃС†РµРЅР°СЂРёРµРІ. Р’ options РїРѕРїР°РґР°РµС‚ С‚РѕР»СЊРєРѕ РІС‹Р±СЂР°РЅРЅС‹Р№ С‡РµСЂРµР· SCENARIO.
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
    `РќРµРёР·РІРµСЃС‚РЅС‹Р№ SCENARIO "${SCENARIO}". Р”РѕСЃС‚СѓРїРЅС‹Рµ СЃС†РµРЅР°СЂРёРё: ${Object.keys(ALL_SCENARIOS).join(", ")}.`,
  );
}

export const options = {
  scenarios: { [SCENARIO]: ALL_SCENARIOS[SCENARIO] },
  // 429 РЅРµ СЃС‡РёС‚Р°РµС‚СЃСЏ РѕС€РёР±РєРѕР№: РїСЂРѕРІРµСЂСЏСЋС‰Р°СЏ СЃРёСЃС‚РµРјР° Р¶РґС‘С‚ Retry-After Рё РїРѕРІС‚РѕСЂСЏРµС‚.
  setResponseCallback: http.expectedStatuses(200, 429),
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  thresholds: {
    http_req_duration: ["p(95)<500"],
    http_req_failed: ["rate<0.01"],
    unmask_ok: ["rate>0.99"],
  },
};

const params = { headers: { "Content-Type": "application/json" }, timeout: "10s" };

// РњРµС‚СЂРёРєРё k6.
const unmaskOk = new Rate("unmask_ok");
const http429 = new Counter("http_429");
const maskDuration = new Trend("mask_duration");
const unmaskDuration = new Trend("unmask_duration");

// POST СЃ СЂРµС‚СЂР°РµРј РЅР° 429: Р¶РґС‘Рј Retry-After (СЃРµРєСѓРЅРґС‹, РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ 1), РјР°РєСЃРёРјСѓРј 2 РїРѕРІС‚РѕСЂР°.
// Р•СЃР»Рё 429 РѕСЃС‚Р°Р»СЃСЏ вЂ” Р·Р°СЃС‡РёС‚С‹РІР°РµРј РІ http_429 Рё РІРѕР·РІСЂР°С‰Р°РµРј null (РёС‚РµСЂР°С†РёСЏ РїСЂРµСЂС‹РІР°РµС‚СЃСЏ).
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
  const text = pickText();
  const id = `${__VU}-${__ITER}-${Date.now()}`;

  // РњР°СЃРєРёСЂРѕРІР°РЅРёРµ.
  const masked = postWithRetry(`${BASE_URL}/process`, JSON.stringify({ payload: text, payload_id: id }));
  if (masked === null) return; // 429 РѕСЃС‚Р°Р»СЃСЏ РїРѕСЃР»Рµ СЂРµС‚СЂР°РµРІ вЂ” Р±РµР· РґРµРјР°СЃРєРёСЂРѕРІР°РЅРёСЏ.
  if (!check(masked, { "mask 200": (r) => r.status === 200 })) return;
  maskDuration.add(masked.timings.duration);

  // Р”РµРјР°СЃРєРёСЂРѕРІР°РЅРёРµ С‚РµРј Р¶Рµ payload_id Рё РїРѕР»СѓС‡РµРЅРЅРѕР№ РјР°СЃРєРѕР№.
  const restored = postWithRetry(
    `${BASE_URL}/process`,
    JSON.stringify({ payload: masked.json("result"), payload_id: id }),
  );
  if (restored === null) return; // 429 РѕСЃС‚Р°Р»СЃСЏ РїРѕСЃР»Рµ СЂРµС‚СЂР°РµРІ.
  const ok = check(restored, {
    "unmask returns original": (r) => r.status === 200 && r.json("result") === text,
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
