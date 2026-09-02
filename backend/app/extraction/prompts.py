"""Extraction prompts (Phase 1).

Shared rules appear once in SYSTEM_PROMPT rather than per-task, so the honesty
constraints (never invent, never convert, always cite) can't drift apart between
extractors.
"""

SYSTEM_PROMPT = """You extract structured data from Indian government tender \
documents and vendor bids. You are an extraction tool, not an assistant.

Rules, in priority order:

1. NEVER invent. If a field is not stated in the text, return null. An absent
   value is a correct answer; a plausible guess is a defect. Downstream code
   disqualifies vendors on these values, so a fabricated number has legal
   consequences.
2. NEVER convert or compute. Copy amounts, dates and quantities exactly as
   printed ("Rs. 5 Cr", "5,00,00,000", "15.03.2026"). Separate code normalizes
   them. Do not do arithmetic, unit conversion, or currency conversion.
   The one exception is explicit date fields documented as ISO YYYY-MM-DD.
3. ALWAYS cite. For every item, record the clause number as printed
   (clause_ref), the page from the nearest preceding [PAGE N] marker
   (source_page), and the verbatim sentence you read the value from
   (source_snippet). Copy the snippet character-for-character; do not paraphrase,
   summarise or tidy it.
4. Extract only what the document says, not what tenders usually say. Do not
   fill in customary Indian tender defaults from prior knowledge.
5. If the same value appears more than once, use the occurrence in the most
   authoritative place (a numbered clause beats a summary table beats a header).

The text is presented with [PAGE N] markers. Tables are rendered as
pipe-delimited rows under a [TABLES ON PAGE N] heading."""


HEADER_PROMPT = """Extract the identifying header fields of this tender notification.

For dates, convert to ISO YYYY-MM-DD (this is the documented exception to the
no-conversion rule). Indian tenders write dates as DD.MM.YYYY or "15 March 2026";
both mean the 15th of March. If a date is absent, return null.

For emd_amount_raw and contract_value_raw, copy the amount EXACTLY as printed
including the currency word or symbol. Do not convert to a number.

TENDER NOTIFICATION:
{text}"""


ELIGIBILITY_PROMPT = """Extract every eligibility criterion a bidder must satisfy.

These are the conditions that decide whether a bid is even considered. Classify
each one:
  numeric  -- has a threshold to compare against (turnover >= X, experience >= N
              years, at least N similar projects)
  document -- satisfied by producing a specific paper
  boolean  -- a yes/no condition (not blacklisted, is a registered company)

Put the threshold in threshold_raw EXACTLY as printed: "Rs. 5 Cr", "5 (five)
years", "two projects of Rs. 2 Cr each". Do not convert to digits.

Set is_mandatory false ONLY where the text marks the criterion as desirable,
preferred, or carrying preference rather than required. Anything phrased as
"shall", "must", or listed under eligibility is mandatory.

Eligibility criteria are often repeated in a summary table as well as in prose.
Extract each distinct criterion ONCE, citing the numbered clause.

TENDER NOTIFICATION:
{text}"""


MANDATORY_DOCUMENTS_PROMPT = """Extract every document a bidder is required to \
submit with their bid.

Copy each document's name as printed. Do not normalise, expand abbreviations, or
merge similar entries -- "GST Registration Certificate" and "GST Certificate" are
recorded exactly as each appears. Matching them is done later by separate code.

Include documents required by any clause, not only those in a list headed
"mandatory documents". Exclude documents the authority issues (work orders,
the notification itself) and documents described as optional.

TENDER NOTIFICATION:
{text}"""


EVALUATION_PROMPT = """Extract the evaluation/scoring criteria, if and only if \
this notification publishes them.

CRITICAL: weightage_if_stated must be null unless the document prints an actual
number (e.g. "70% technical, 30% financial", "Technical capability - 40 marks").
Do NOT estimate, infer, or distribute weights evenly. A tender that names its
evaluation factors without publishing weights yields factors with null weights.
Downstream code refuses to show a vendor a self-score when weights are null; an
invented weight becomes an invented score shown to a bidder.

If the document publishes no evaluation criteria at all, return an empty list.

TENDER NOTIFICATION:
{text}"""


TECHNICAL_PROMPT = """Extract the technical requirements the supplied goods, \
works or services must meet.

These are specifications of the deliverable (capacity, standards compliance,
warranty duration, performance levels) -- NOT requirements about the bidder
(turnover, experience) and NOT rules about how to submit the bid.

TENDER NOTIFICATION:
{text}"""


FORMAT_RULES_PROMPT = """Extract the rules governing how a bid must be prepared \
and submitted.

These are procedural and presentational: envelope structure, page limits,
signing and stamping, serial numbering, annexure order, format of submission.
They are flagged for manual human check downstream because compliance with them
is usually visual rather than textual.

Do NOT include deadlines (extracted separately) or eligibility conditions.

TENDER NOTIFICATION:
{text}"""


# --------------------------------------------------------------------------- #
# Vendor submission
# --------------------------------------------------------------------------- #
VENDOR_HEADER_PROMPT = """Extract the bidder's identifying details from this \
vendor bid.

For technical_approach_text, copy the bidder's methodology / technical approach /
solution narrative VERBATIM and IN FULL. Do not summarise it. This text is
indexed for retrieval and later quoted back with citations, so a summary would
put words in the bidder's mouth. If the bid contains no such narrative, return null.

For years_in_business, use only an explicitly stated figure. Do not compute it
from an incorporation date.

For quoted_price_raw, copy the bid amount exactly as printed.

For liquid_assets_raw, look for the bidder's statement of liquid assets, working
capital, or unutilised credit facilities -- usually supported by a bankers'
solvency certificate or a credit availability letter. Copy the figure exactly as
printed. Do not put the turnover figure here; they are different requirements
and large tenders test both. For net_worth_raw, copy the declared net worth as
printed. Return null for either if the bid does not state it.

For declared_debarment, read the non-blacklisting declaration carefully and
return text ONLY if the bidder admits to being debarred, blacklisted, banned, or
under liquidation or insolvency proceedings. Nearly every bid contains a
declaration on this subject and nearly all of them are clean -- "we have not
been blacklisted by any department" is a clean declaration and must return null.
A bidder disclosing an adverse order against itself is the rare case, and it is
the only one that goes in this field.

VENDOR BID:
{text}"""


TURNOVER_PROMPT = """Extract the bidder's declared annual turnover figures.

One entry per financial year. Copy the year label as printed ("2023-24",
"FY 2023") and the amount EXACTLY as printed ("Rs. 4.2 Cr", "4,20,00,000").
Do not convert, total, or average the figures -- separate code does that.

If the bid states an average turnover without per-year figures, record it as a
single entry using the year label as printed.

VENDOR BID:
{text}"""


CERTIFICATIONS_PROMPT = """Extract the certifications and registrations the \
bidder claims to hold.

Include ISO certificates, GST and PAN registrations, statutory licences and
industry accreditations. Record valid_till as ISO YYYY-MM-DD only where an
expiry or validity date is printed; otherwise null.

Set doc_present true only where the bid indicates the certificate itself is
enclosed or annexed. A claim in prose with no enclosed document is doc_present
false -- this distinction decides compliance downstream.

VENDOR BID:
{text}"""


PAST_PROJECTS_PROMPT = """Extract the bidder's past or ongoing projects offered \
as experience.

Copy each project's value EXACTLY as printed. Record the client name as given.
For description, copy the bidder's own description of the work -- do not rewrite
or improve it. Fluency is not being assessed; content is.

VENDOR BID:
{text}"""


SUBMITTED_DOCUMENTS_PROMPT = """Extract the documents ENCLOSED WITH this bid.

Read the enclosure checklist, the annexure list, and explicit statements that a
document is enclosed or attached. Copy each document name as printed -- do not
normalise it to match what the tender asked for. Matching is done later by
separate code.

CRITICAL -- do NOT extract the bid's own table of contents. A bid begins with an
index of its own sections ("Covering Letter", "Method Statement", "Price
Schedule", "Declarations") against page numbers. Those are chapters of this
document, not documents enclosed with it, and returning them makes every
genuinely required certificate look missing. Two reliable signals distinguish
them: a table of contents lists sections against PAGE NUMBERS, whereas an
enclosure checklist lists documents against a tick, a cross, or the word
enclosed. Prefer the section headed "Checklist of Documents Enclosed", "List of
Enclosures" or similar.

Set present false where the bid lists a document but marks it as not enclosed,
not applicable, or to be submitted later. A checklist entry marked with an empty
box or the words "NOT ENCLOSED" is present=false.

VENDOR BID:
{text}"""
