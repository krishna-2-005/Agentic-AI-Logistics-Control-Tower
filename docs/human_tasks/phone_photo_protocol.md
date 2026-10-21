# Phone-photo collection protocol (document extraction)

Goal: 10 real freight documents (invoices, receipts, delivery notes or bills of lading)
photographed the way a person at a loading dock would, so the document agent can be scored on
something other than synthetic scans. Nothing below should be simulated: if you cannot get 10
real documents, say how many you got.

## What counts

* Real paper documents from a real business transaction (yours, a family business, a friend's
  shop). Printed or handwritten. Indian GST invoices, transport receipts and lorry receipts are
  all useful.
* Ten different documents, not ten photos of one. Where possible vary the issuer, the layout
  and the language mix (English, Hindi, both).
* You must be allowed to photograph them. Ask the owner, and tell them what the photos are for.

## How to photograph (vary these across the set)

Take one photo per document, and for at least four documents take a second photo with a
different condition, so each document has a "good" and a "bad" shot:

| condition | how |
|---|---|
| good | flat on a table, daylight or a lamp, camera parallel to the page, whole page in frame |
| angled | camera at about 30 degrees from the page, perspective visible |
| dim | indoor evening light, no flash |
| glare | a lamp or window reflecting on glossy paper |
| folded or creased | folded in three, photographed unfolded but creased |
| partial | page edge slightly cut off (as people do under time pressure) |

Use the phone's normal camera in the default mode; do not use a scanner app, filters or
automatic cropping. Keep the original resolution. Hold steady; retake only if the photo is
unreadable to you.

## Privacy: redact before the file leaves your phone

Before saving to the shared folder, cover with an opaque black box (the phone's markup tool is
fine) any of: personal phone numbers, personal addresses, bank account and card numbers,
Aadhaar and PAN numbers, signatures, and the names of private individuals. Keep company names,
GSTINs, amounts, dates, invoice numbers and routes: those are what the agent is read against.
If a document cannot be redacted and still be useful, do not use it. Never commit a photo
that shows anything you did not redact.

## Naming and where to put them

Put the files in `data/phone_photos/` (this folder is git-ignored; nothing is committed
automatically). Name them `P01_good.jpg`, `P01_angled.jpg`, `P02_good.jpg` and so on, where
`P01` is the document number. Keep a `data/phone_photos/index.csv` with these columns:

`doc_id, file, condition, document_type, language, issuer_type, redacted (yes/no), permission_given (yes/no)`

Do not rename files after the index is written.

## Ground truth (the part only you can do)

For each document, type into `data/phone_photos/truth.csv` what the document actually says,
reading the paper and not the extraction output: `doc_id, invoice_number, date, shipper,
consignee, origin, destination, pieces, weight_kg, freight_charge, total_amount`. Leave a cell
empty if the paper does not show it. Do this before running the agent on the photos, so the
truth is not influenced by the agent's answer.

## After collection

Tell the repository owner the number of documents and photos. The evaluation will be run once
on the finished set; the result will be reported with n and a Wilson interval, whatever it is.
