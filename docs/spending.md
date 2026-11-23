# Spending

The **Spending** page turns GBP bank transactions into monthly, category, pace and income charts.
Transactions are stored as integer pence, separately from net-worth snapshots, so a failed sync
never touches balances or history. Pick a period beside the month picker (month, 3M, 6M, YTD, 1Y,
all). Charts exclude pending payments and transfers, and count refunds in the month received.

## Sources

- **Monzo:** the scheduler syncs recent transactions (the last 89 days, to settle pending ones)
  whenever Monzo is due. Monzo only allows full history in the minutes after authenticating, so
  `python -m networth monzo-auth "Monzo"` imports everything straight away.
- **Lunch Flow** (Santander, Amex and other banks): set `LUNCHFLOW_API_KEY` in `.env` (from a Lunch
  Flow *REST API destination*), then open **Spending → gear → Bank connections** and pick the cards
  to import. Accounts link by `account_id` / `account_ids` in `accounts.yaml`. The same feed gives
  balances (`type: lunchflow`); credit cards are negative when money is owed. Sync is hourly, or
  press **sync** on a bank pill. Blank import dates fetch all available history.
- **CSV statements** (manual cash accounts): gear → **Statements**, map columns and preview. Needs a
  header row, date, description and either a signed amount or separate in/out columns. Dates may be
  DD/MM/YYYY or YYYY-MM-DD. Limit 5 MB / 10,000 rows. Re-importing the same file is safe.

## Categories and transfers

Your corrections always win. Everything else is suggested (shown in italics), and worked out at
read time, so improving the rules improves past transactions too.

- Uncategorised bank transactions take the category Monzo or you gave the same merchant, then fall
  back to keyword rules (`networth/categorise.py`).
- An opposite amount in another account within three days becomes a transfer when there is
  evidence it's your own money: a shared reference, a card repayment, or one side already marked.
  Payments to investment platforms are *Savings* transfers; money back from a merchant is a refund.
  Other matches stay suggestions for you to review.

## Recurring payments

Weekly and monthly patterns need three settled payments, quarterly and annual ones need two.
Confirm a suggestion to count it in your monthly commitments, or dismiss or cancel it. Use a
transaction's recurring icon to mark a merchant as **Monthly spend** or **Monthly subscription**, or
**Not recurring** to suppress suggestions. A payment that goes missing turns inactive once later
account activity passes its expected date plus a grace period (weekly 14 days, monthly 35,
quarterly 45, annual 60). A new payment revives it.

Inferred payments are estimates from recorded history, not a bank mandate feed.

## Back up

History and rules live in Postgres, so back that up. The hide-amounts toggle in the header covers
spending too.
