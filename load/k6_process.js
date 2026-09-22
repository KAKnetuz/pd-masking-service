// Нагрузочный сценарий под профиль проверяющей системы.
// Одна итерация = синхронная пара «маскирование → демаскирование» с одним payload_id.
// Сценарий выбирается переменной окружения SCENARIO: checker (по умолчанию), rps1000, rps2000.
// Запуск:
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

// Короткие фразы с одним типом ПД (примеры 1, 4, 9, 10, 16, 18, 19, 20, 22, 23, 26, 27, 28
// из tests/fixtures/span_reference.yaml). Примеры 27 и 28 — «ловушки» без ПД.
const SHORT_SAMPLES = [
  "Клиент Иванов Иван Иванович обратился в банк.",
  "Дата рождения: 12.03.1990.",
  "Паспорт 4509 123456.",
  "Паспорт серия 4510 номер 654321.",
  "Водительское удостоверение 77 АВ 123456.",
  "Проживает по адресу: 350000, Россия, г. Краснодар, ул. Красная, д. 10, кв. 5.",
  "Пишите на ivan.petrov@mail.ru.",
  "Телефон +7 (916) 123-45-67.",
  "ИНН 500100732259.",
  "Номер карты 2200 1234 5678 9019.",
  "Карта 2200 1234 5678 9019, держатель IVAN IVANOV, CVV 123, пин-код 4321.",
  "Александр Пушкин написал «Евгения Онегина».",
  "Отделение банка находится по адресу: г. Москва, ул. Каланчевская, д. 27.",
];

// Сложное предложение (пример 30 из span_reference.yaml).
const COMPLEX_SAMPLE =
  "Клиент Сидоров Пётр Алексеевич, 05.11.1985 г.р., паспорт серия 4511 номер 987654 выдан ОУФМС России по г. Краснодару 20.01.2010, код подразделения 230-001, проживает: г. Краснодар, ул. Северная, д. 5, кв. 12, тел. +7 918 555-44-33, email sidorov@yandex.ru, ИНН 500100732259, просит перевыпустить карту 2200 1234 5678 9019.";

// Длинный текст ~20 000 символов: сложное предложение, повторённое нужное число раз.
let LONG_TEXT = "";
while (LONG_TEXT.length < 20000) {
  LONG_TEXT += COMPLEX_SAMPLE + " ";
}

// Выбор текста: 60% — короткие фразы, 35% — сложное предложение, 5% — длинный текст.
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

// Описания всех сценариев. В options попадает только выбранный через SCENARIO.
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
    `Неизвестный SCENARIO "${SCENARIO}". Доступные сценарии: ${Object.keys(ALL_SCENARIOS).join(", ")}.`,
  );
}

export const options = {
  scenarios: { [SCENARIO]: ALL_SCENARIOS[SCENARIO] },
  // 429 не считается ошибкой: проверяющая система ждёт Retry-After и повторяет.
  setResponseCallback: http.expectedStatuses(200, 429),
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
  thresholds: {
    http_req_duration: ["p(95)<500"],
    http_req_failed: ["rate<0.01"],
    unmask_ok: ["rate>0.99"],
  },
};

const params = { headers: { "Content-Type": "application/json" }, timeout: "10s" };

// Метрики k6.
const unmaskOk = new Rate("unmask_ok");
const http429 = new Counter("http_429");
const maskDuration = new Trend("mask_duration");
const unmaskDuration = new Trend("unmask_duration");

// POST с ретраем на 429: ждём Retry-After (секунды, по умолчанию 1), максимум 2 повтора.
// Если 429 остался — засчитываем в http_429 и возвращаем null (итерация прерывается).
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

  // Маскирование.
  const masked = postWithRetry(`${BASE_URL}/process`, JSON.stringify({ payload: text, payload_id: id }));
  if (masked === null) return; // 429 остался после ретраев — без демаскирования.
  if (!check(masked, { "mask 200": (r) => r.status === 200 })) return;
  maskDuration.add(masked.timings.duration);

  // Демаскирование тем же payload_id и полученной маской.
  const restored = postWithRetry(
    `${BASE_URL}/process`,
    JSON.stringify({ payload: masked.json("result"), payload_id: id }),
  );
  if (restored === null) return; // 429 остался после ретраев.
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
```

Now let me update the `.gitignore` to add `load/results/`.

<｜DSML｜tool_calls>
<｜DSML｜invoke name="edit">
<｜DSML｜parameter name="path" string="true">C:\Users\e.mazniak\Desktop\проект\pd-masking-service-git\.gitignore