// Нагрузочный сценарий по контракту: пара «маскирование → демаскирование» с одним payload_id.
// 500 итераций/с = 1000 RPS. Запуск (с другой машины, не с сервера):
//   docker run --rm -i -e TARGET=http://51.250.4.227 grafana/k6 run - < load/k6_process.js
import http from "k6/http";
import { check } from "k6";
import exec from "k6/execution";

const TARGET = __ENV.TARGET || "http://localhost";
const RATE = Number(__ENV.RATE || 500);

const SAMPLES = [
  "Клиент Иванов Иван Иванович, паспорт 4509 123456",
  "Паспорт: серия 45 09 номер 123456, выдан ОВД района Хамовники г. Москвы 12.03.2010, код подразделения 770-001",
  "Дата рождения: 12 марта 1990 г., место рождения: г. Нижний Новгород",
  "Адрес: 123456, г. Москва, ул. Ленина, д. 5, кв. 12",
  "Мой email ivanov.ivan@mail.ru, телефон +7 (916) 123-45-67",
  "ИНН 500100732259, карта 4276 1234 5678 9010, CVV 123, пин-код 1234",
  "Держатель карты: IVAN IVANOV, водительское удостоверение 77 АВ 123456",
  "Александр Пушкин написал «Евгения Онегина».",
];

export const options = {
  scenarios: {
    pairs: {
      executor: "constant-arrival-rate",
      rate: RATE,
      timeUnit: "1s",
      duration: __ENV.DURATION || "5m",
      preAllocatedVUs: 400,
      maxVUs: 2000,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1000", "p(99)<2000"],
    checks: ["rate>0.99"],
  },
};

const params = { headers: { "Content-Type": "application/json" }, timeout: "10s" };

export default function () {
  const text = SAMPLES[exec.scenario.iterationInTest % SAMPLES.length];
  const id = `k6-${exec.vu.idInTest}-${exec.scenario.iterationInTest}`;

  const masked = http.post(`${TARGET}/process`, JSON.stringify({ payload: text, payload_id: id }), params);
  if (!check(masked, { "mask 200": (r) => r.status === 200 })) return;

  const restored = http.post(
    `${TARGET}/process`,
    JSON.stringify({ payload: masked.json("result"), payload_id: id }),
    params,
  );
  check(restored, { "unmask returns original": (r) => r.status === 200 && r.json("result") === text });
}
