import assert from "node:assert/strict";
import test from "node:test";
import {
  dollars,
  minutesBetween,
  problemSlug,
  refundIfCancelled,
  stripeUrl,
} from "../apps/web/app/coaching/format.ts";
import { birthYearFrom } from "../apps/web/lib/google-birthday.ts";

test("Google birthday gives only a plausible year, primary first", () => {
  const today = new Date("2026-09-25T00:00:00Z");
  const entry = (year, primary) => ({
    metadata: primary ? { primary: true } : {},
    date:
      year === undefined ? { month: 3, day: 4 } : { year, month: 3, day: 4 },
  });
  const from = (list) => birthYearFrom({ birthdays: list }, today);
  assert.equal(from([entry(1990), entry(1985, true)]), 1985);
  assert.equal(from([entry(undefined, true), entry(1990)]), 1990);
  assert.equal(from([entry(undefined, true)]), null);
  assert.equal(from([entry(1899), entry(2027)]), null);
  assert.equal(from([entry("1990")]), null);
  assert.equal(birthYearFrom({}, today), null);
  assert.equal(birthYearFrom(null, today), null);
});

const now = Date.parse("2026-09-24T12:00:00Z");
const hour = 60 * 60 * 1000;
const at = (offset) => new Date(now + offset).toISOString();

test("player refund follows the 24 hour rule", () => {
  const booking = { status: "confirmed", price_cents: 6000 };
  assert.equal(
    refundIfCancelled({ ...booking, starts_at: at(25 * hour) }, now),
    6000,
  );
  assert.equal(
    refundIfCancelled({ ...booking, starts_at: at(24 * hour) }, now),
    0,
  );
  assert.equal(refundIfCancelled({ ...booking, starts_at: at(hour) }, now), 0);
  assert.equal(
    refundIfCancelled(
      { ...booking, status: "pending_payment", starts_at: at(hour) },
      now,
    ),
    null,
  );
});

test("money and duration labels", () => {
  assert.equal(dollars(4500), "$45");
  assert.equal(dollars(4550), "$45.50");
  assert.equal(minutesBetween(at(0), at(1.5 * hour)), 90);
});

test("only https Stripe pages receive the browser", () => {
  assert.equal(
    stripeUrl("https://checkout.stripe.com/c/pay/cs_test_1"),
    "https://checkout.stripe.com/c/pay/cs_test_1",
  );
  assert.ok(stripeUrl("https://connect.stripe.com/setup/e/acct_1"));
  for (const bad of [
    "http://checkout.stripe.com/x",
    "https://evilstripe.com/x",
    "https://stripe.com.evil.invalid/x",
    "javascript:alert(1)",
    "/coaching",
    null,
  ]) {
    assert.equal(stripeUrl(bad), null, String(bad));
  }
});

test("problem slug lets the booking form spot unconfigured payments", () => {
  assert.equal(
    problemSlug({
      type: "https://shoulder.local/problems/payments-unavailable",
      status: 503,
    }),
    "payments-unavailable",
  );
  assert.equal(problemSlug({ type: 7 }), null);
  assert.equal(problemSlug(null), null);
  assert.equal(problemSlug("oops"), null);
});
