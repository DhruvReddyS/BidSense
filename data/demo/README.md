# BidSense demo pack

This folder is arranged for a live demonstration. Each numbered tender folder
is self-contained and has the same layout:

- `01_notification/` — upload this document first.
- `02_quick_demo_bids/` — five bids covering pass, numeric failure, missing
  evidence, debarment, and a borderline pass.
- `03_extended_test_bids/` — ten additional bids for larger batch and
  repeatability testing.
- `answer_key.csv` — expected Level 1 outcome and reason for all 15 bids.
- `DEMO_GUIDE.md` — tender-specific description and presentation sequence.

## Recommended live demo

Use `02_ghmc_led_street_lights`. Its notification is shorter than the solar
tender and its five quick bids give a clear mix of outcomes.

1. Upload the single file inside `01_notification`.
2. Open the resulting tender and select **Company review**.
3. Bulk-upload all five files from `02_quick_demo_bids`.
4. Run **Level 1 evaluation** and compare the results with `answer_key.csv`.
5. Prepare a Level 2 qualified pool with a target size of two.
6. Ask a Level 3 evidence question and open one cited source page.
7. Export the committee PDF.

The answer keys are demo verification material. Do not show them before the
system produces its decisions if the audience should see a blind evaluation.
