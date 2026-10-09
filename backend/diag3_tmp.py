from app.compliance.matching import match_document
pairs = [
  # (tender requirement, bid enclosure that a human would accept)
  ("single PDF file of compliance sheet", "clause-wise compliance statement"),
  ("BOQ file", "Main Price Bid comprising of Schedule No 1 to 4 of the Price Schedule"),
  ("Covering Letter", "Bid Form for first Part"),
  ("Original Non-Refundable Tender Processing Fee", "documentary evidence of payment of EMD"),
  ("Original Non-Refundable Cost of Tender Document", "documentary evidence of payment of EMD"),
  ("undertaking to the effect that (i) neither the bidder themselves nor their allied agencies",
   "undertaking on Genuineness of the certificates"),
]
print("requirement  ->  candidate : matched? score method")
for req, cand in pairs:
    r = match_document(req, [cand], use_embeddings=True)
    print(f"\n  {req[:58]}")
    print(f"    vs {cand[:58]}")
    print(f"    matched={r.matched} score={r.score:.3f} method={r.method} needs_review={r.needs_review}")
