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


# The instruction-only version, kept so the few-shot prompt below can be
# measured against it rather than assumed better. `scripts.benchmark_extraction
# --prompt both` runs the pair on the same documents and the same selected
# pages. See the header of that script for why this control matters: a
# capability gap and a prompting gap are indistinguishable from outside.
HEADER_PROMPT_NO_EXAMPLES = """Extract the identifying header fields of this tender notification.

For dates, convert to ISO YYYY-MM-DD (this is the documented exception to the
no-conversion rule). Indian tenders write dates as DD.MM.YYYY or "15 March 2026";
both mean the 15th of March. If a date is absent, return null.

For emd_amount_raw and contract_value_raw, copy the amount EXACTLY as printed
including the currency word or symbol. Do not convert to a number.

TENDER NOTIFICATION:
{text}"""


HEADER_PROMPT = """Extract the identifying header fields of this tender notification.

For dates, convert to ISO YYYY-MM-DD (this is the documented exception to the
no-conversion rule). Indian tenders write dates as DD.MM.YYYY or "15 March 2026";
both mean the 15th of March. If a date is absent, return null.

For emd_amount_raw and contract_value_raw, copy the amount EXACTLY as printed
including the currency word or symbol. Do not convert to a number.

WHERE THESE FIELDS ACTUALLY SIT. Indian tenders put them in a "Notice Inviting
Tender" grid or a key-dates table near the front, as label/value rows rather
than sentences. The label rarely matches the field name: the submission deadline
is printed as "Last Date and Time for uploading of Bids" or "Bid Submission End
Date", and the EMD as "Earnest Money" inside a cost table. Read the value from
the row whose LABEL means the field, not from the row whose label looks like it.

Watch for two rows that both look like a deadline. "Last Date for submission of
EMD" is not the bid deadline; "Last Date and Time for uploading of Bids" is.

WORKED EXAMPLES. These are illustrations of the shape only -- never copy a value
from them into your answer.

Example A, from a page printed as a table:

    Name of Work                              Construction of internal roads
    Estimated Cost                            Rs. 84,21,900/-
    Earnest Money                             Rs. 1,68,438/-
    Last Date and Time for receipt of Queries 03 July 2025 (11:00 Hours)
    Last Date and Time for uploading of Bids  09 July 2025 (18:30 Hours)

  ->  submission_deadline    : "2025-07-09"
      pre_bid_query_deadline : "2025-07-03"
      emd_amount_raw         : "Rs. 1,68,438/-"
      contract_value_raw     : "Rs. 84,21,900/-"

Example B, where the authority appears only in the letterhead and the dates are
written differently:

    OFFICE OF THE EXECUTIVE ENGINEER, PUBLIC WORKS DIVISION, NAGPUR
    e-Tender Notice No. PWD/NGP/2025-26/41
    Bid submission end date : 14.02.2026 upto 15:00 hrs
    EMD : Rupees Two Lakh Fifty Thousand only (Rs. 2,50,000/-)

  ->  tender_id            : "PWD/NGP/2025-26/41"
      issuing_authority    : "Office of the Executive Engineer, Public Works Division, Nagpur"
      submission_deadline  : "2026-02-14"
      emd_amount_raw       : "Rs. 2,50,000/-"

Example C, a tender that genuinely does not state a pre-bid date:

    Tender ID : 2026_HGCL_884213_1
    Last date of submission : 30-11-2026

  ->  tender_id              : "2026_HGCL_884213_1"
      submission_deadline    : "2026-11-30"
      pre_bid_query_deadline : null
      emd_amount_raw         : null

Null is the right answer when the document does not say. It is not the right
answer when the document says it somewhere you did not look.

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


CORRIGENDUM_HEADER_PROMPT = """Extract the identifying fields of this CORRIGENDUM \
(an amendment to a tender notification that has already been published).

corrigendum_id is the amendment's OWN reference number ("Corrigendum No. 2",
"Addendum-I"), not the tender's. parent_tender_id is the reference of the tender
being amended, copied exactly as printed here.

For submission_deadline, pre_bid_query_deadline, emd_amount_raw and
contract_value_raw, return the NEW value ONLY if this corrigendum states one.
Return null where the corrigendum does not mention that field -- null means
"unchanged", and a value invented here would be recorded as an amendment that
never happened, which is worse than missing one.

Do NOT return the original tender's values from the surrounding recital text.
Only the amended values.

CORRIGENDUM:
{text}"""


CORRIGENDUM_CHANGES_PROMPT = """List every amendment this corrigendum makes to the \
original tender.

One entry per change. `subject` is what is being amended, in the document's own
words. `new_value` is the amended value exactly as printed. `old_value` is the
previous value ONLY where the corrigendum itself prints it -- corrigenda often
say "in place of" or "instead of", and that is the only source you may use.
Where the old value is not printed, return null; separate code holds the
original tender and computes the difference.

change_kind: 'extended' for a deadline moved later, 'amended' for a value
replaced, 'added' for a requirement introduced, 'deleted' for one withdrawn.

Do not list the corrigendum's own recitals, covering text, or instructions on
how to download it. Only the substantive changes to the tender's terms.

CORRIGENDUM:
{text}"""
