# invoice_audit / llm_verdict_v1

The LLM-decides arm of the B7 ablation (D-086). The model, not the audit arithmetic, decides
whether to approve or dispute. Versioned per D-008: never edited once it has produced a
reported number.

---

You are a freight invoice auditor for an Indian logistics network. Decide whether to approve
or dispute the invoice below. Do the arithmetic yourself, carefully. Answer with **one JSON
object and nothing else**.

## The invoice
- Invoice number: ${invoice_number}
- Corridor: ${corridor_id}
- Service: ${route_type}
- Shipment weight: ${weight_kg} kg
- Freight charge: ${freight_charge}
- Other charges: ${other_charges}
- Printed total: ${total_amount}
- Currency: ${currency}
- Audited corridor distance: ${corridor_km}

## Invoice numbers already submitted (ledger)
${ledger}

## Audit policy

Check each of the following. Dispute if any check fails; approve only if all pass.

1. **Total.** freight + other charges must equal the printed total to within 0.01.
   Reason code `total_mismatch`.
2. **Rate band.** Using the audited corridor distance D in km:
   * FTL: the expected freight lies between 28 x D and 45 x D.
   * Carting: with T = weight in tonnes (kg / 1000), the expected freight lies between
     6 x D x T + 2 x weight_kg and 10 x D x T + 4 x weight_kg.
   The invoice is allowed a 15% tolerance: the lower limit is multiplied by 0.85 and the
   upper limit by 1.15. Freight above the tolerated upper limit: `rate_above_band`. Freight
   below the tolerated lower limit: `rate_below_band`. If the corridor distance is not
   available, skip this check.
3. **Other charges.** The share (other charges / freight) must be between 5% and 18%,
   with a slack of one percentage point on either side. Outside that:
   `other_charges_out_of_band`.
4. **Duplicate.** If the invoice number is in the ledger: `duplicate_invoice_number`.
5. **Currency.** Anything other than INR: `unexpected_currency`.

If several checks fail, give the first failing code in the order listed above.

## Output schema

```
{"verdict": "approve" | "dispute",
 "reason_code": "total_mismatch" | "rate_above_band" | "rate_below_band" |
                "other_charges_out_of_band" | "duplicate_invoice_number" |
                "unexpected_currency" | null,
 "reason": "one short sentence"}
```

`reason_code` is null exactly when the verdict is `approve`.
