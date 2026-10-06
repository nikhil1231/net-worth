import test from 'node:test'
import assert from 'node:assert/strict'
import { moneyFormatter } from '../src/money.ts'

const rates = { GBP: 1, USD: 1.25, EUR: 1.1 }

test('GBP and USD format the same stored valuation without changing it', () => {
  assert.equal(moneyFormatter('GBP', rates).money(100), '£100')
  assert.equal(moneyFormatter('USD', rates).money(100), '$125')
  assert.equal(moneyFormatter('USD', rates).moneyExact(100), '$125.00')
})

test('dollar sandbox input converts back to canonical pounds', () => {
  const money = moneyFormatter('USD', rates)
  assert.equal(money.toGBP(125), 100)
  assert.equal(money.toDisplay(money.toGBP(125)), 125)
  assert.equal(money.toGBP(125) / 10, 10) // Ten units at £10 each.
})

test('native US dollar prices are not converted twice', () => {
  assert.equal(moneyFormatter('GBP', rates).nativeMoney(125, 'USD'), '£100.00')
  assert.equal(moneyFormatter('USD', rates).nativeMoney(125, 'USD'), '$125.00')
})

test('London pence prices convert through pounds', () => {
  assert.equal(moneyFormatter('USD', rates).nativeMoney(10000, 'GBp'), '$125.00')
  assert.equal(moneyFormatter('GBP', rates).nativeMoney(10000, 'GBX'), '£100.00')
})

test('signed changes and compact chart labels use the selected currency', () => {
  const money = moneyFormatter('USD', rates)
  assert.equal(money.signedMoney(-100), '−$125')
  assert.equal(money.moneyCompact(100000), '$125K')
})

test('missing dollar rate fails rather than presenting pounds as dollars', () => {
  assert.throws(() => moneyFormatter('USD', { GBP: 1 }), /exchange rate/)
})
