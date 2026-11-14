const COMPANY_DEMO_BIDDERS: Record<string, string> = {
  "SOLAR-VENDOR-DRAFT-1": "Orion Solar EPC Private Limited",
  "SOLAR-VENDOR-DRAFT-2": "Deccan Sun Infrastructure Limited",
  "SOLAR-VENDOR-DRAFT-3": "HelioWorks Energy Systems Private Limited",
  "SOLAR-VENDOR-DRAFT-4": "Aarohan Renewables Private Limited",
};

export function companySubmissionLabel(vendorId: string, vendorName?: string | null) {
  const demoBidder = COMPANY_DEMO_BIDDERS[vendorId];
  if (demoBidder) return demoBidder;

  const name = vendorName?.trim();
  if (name && !/\bdraft\s*\d+\b/i.test(name)) return name;
  return `Vendor submission ${vendorId}`;
}
