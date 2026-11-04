# Example investigation report

This is the shape of the report the playbook produces. The scenario and data are fictional.

```
TICKET: ABC123-45678: express shipping greyed out at checkout for Northwind
ASK: Requester wants to select "Express (2-day)" shipping on the Northwind account
CAUSE: Data. The account's shipping profile has express_enabled = 0, so the checkout
       template renders the option disabled. It was switched off yesterday.
EVIDENCE:
  - templates/checkout/shipping.html:57: adds class "disabled" when data-express="0"
  - app/checkout/shipping.py:31: data-express comes from shipping_profiles.express_enabled
  - SELECT id, express_enabled, updated_at FROM shipping_profiles WHERE account_id = 1187
      → 52 | 0 | 2026-11-02 18:05
  - A comparable account's profile (id 49) has express_enabled = 1 and the option works
FIX: UPDATE shipping_profiles SET express_enabled = 1 WHERE id = 52;   -- for review, not run
VERIFY AFTER FIX: reload checkout for Northwind; Express is selectable and the rate shows
CONFIDENCE: high. Code path traced and the data matches; the 11-02 edit explains "worked yesterday".
UNVERIFIED: who changed the profile on 11-02, and why
OPEN: confirm with the account owner that express shipping should be on
```
