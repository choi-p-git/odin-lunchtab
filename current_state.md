# Current State Analysis

## Odin Cloud to LunchTab Balance Transfer Process

### Executive Summary

The current balance migration process from Odin Cloud to LunchTab is a fully manual, record-by-record workflow requiring information to be reconciled across multiple independent data sources. The process relies on repeated user lookups, manual validation, and manual data entry before balances can be transferred into the LunchTab import file.

Based on a timed sample, the current processing rate is approximately **8 accounts every 5 minutes**, equating to roughly **96 accounts per hour** under uninterrupted working conditions.

The current migration file contains **1,478 Odin accounts**, including active users, legacy users, and recently graduated users who ultimately do not require migration. Because inactive accounts cannot be easily identified at the beginning of the workflow, every account must still be investigated manually before a decision can be made.

This creates significant labor cost, limits throughput, and introduces multiple opportunities for human error.

---

# Current Workflow

For each Odin account, the operator performs the following sequence:

1. Open the Odin balance spreadsheet.
2. Locate the current account.
3. Record the user's remaining balance.
4. Switch to the LunchTab user export spreadsheet.
5. Search using the Odin identifier.
6. Retrieve the associated LunchTab login barcode.
7. Retrieve the account holder's name.
8. Retrieve the associated Family Code.
9. Switch to the LunchTab balance import CSV.
10. Search for the matching Family Code.
11. Verify the correct family record.
12. Manually copy the balance into the destination CSV.
13. Repeat for the next account.

Accounts belonging to legacy users or graduated users still require several of the above lookup steps before determining that no balance transfer is necessary.

---

# Systems Involved

The current process requires continual navigation between three separate files:

* Odin balance export spreadsheet
* LunchTab user mapping spreadsheet
* LunchTab balance import CSV

These files contain different identifiers, requiring manual cross-referencing before a transfer can occur.

Identifier translation currently follows this chain:

Odin User ID

↓

LunchTab Login Barcode

↓

Account Name

↓

Family Code

↓

LunchTab Balance Import Record

---

# Time Study

### Sample Observation

Measured processing rate:

* 8 accounts processed
* 5 minutes elapsed

Equivalent throughput:

* 1.6 accounts per minute
* 96 accounts per hour

---

# Estimated Processing Time

Current migration dataset:

**1,478 Odin accounts**

Estimated processing time assuming uninterrupted work:

| Metric                    |       Value |
| ------------------------- | ----------: |
| Accounts per hour         |          96 |
| Total accounts            |       1,478 |
| Estimated processing time | ~15.4 hours |

This estimate assumes:

* No interruptions
* No validation corrections
* No lookup mistakes
* No duplicate investigation
* Constant operator speed

Actual production time is expected to exceed this estimate due to normal operational interruptions and exception handling.

---

# Operational Bottlenecks

The majority of processing time is consumed by:

### 1. Identifier Translation

No common unique identifier exists between the Odin balance export and the LunchTab balance import.

Each account requires several intermediate lookups before reaching the destination record.

---

### 2. Multiple File Navigation

Operators continuously alternate between three documents.

This increases cognitive load and slows overall processing speed.

---

### 3. Manual Searching

Every account requires repeated search operations.

Examples include:

* User ID
* Login Barcode
* Name
* Family Code

Each search introduces additional processing time.

---

### 4. Legacy Account Investigation

The migration source contains users who no longer require migration, including:

* Legacy accounts
* Graduated users

Because these accounts cannot be automatically filtered beforehand, operator effort is still spent locating and validating them.

---

### 5. Manual Data Entry

Final balances are manually copied into the LunchTab import CSV.

Manual transcription creates additional opportunities for:

* Incorrect balances
* Wrong destination row
* Missed records
* Duplicate updates

---

# Risks

## Human Error

Repeated manual lookups increase the likelihood of:

* Incorrect family matching
* Incorrect balance entry
* Skipped accounts
* Duplicate processing

---

## Scalability

Processing time scales almost linearly with the number of accounts.

Larger migrations require proportionally more labor.

---

## Audit Difficulty

Because transfers are completed manually, reconstructing how an individual balance was transferred requires reviewing multiple spreadsheets and operator work.

---

## Resource Utilization

The process occupies staff time performing repetitive administrative work rather than higher-value operational activities.

---

# Quantitative Summary

| Metric                      |                          Current State |
| --------------------------- | -------------------------------------: |
| Source files                |                                      3 |
| Manual searches per account |                               Multiple |
| Identifier translations     | Odin ID → Barcode → Name → Family Code |
| Timed sample                |                 8 accounts / 5 minutes |
| Processing rate             |                      ~96 accounts/hour |
| Accounts to review          |                                  1,478 |
| Estimated labor             |                    ~15.4 hours minimum |
| Manual copy/paste required  |                                    Yes |
| Legacy account filtering    |                                 Manual |
| Human error potential       |                                   High |

---

# Current State Assessment

The current migration process is highly manual and depends on repeated cross-referencing between unrelated datasets. Throughput is constrained primarily by identifier translation, document switching, and manual searching rather than by the balance transfer itself.

Based on the measured processing rate, the current migration would require approximately **15.4 hours of uninterrupted processing** for the existing dataset of 1,478 accounts. Actual completion time is expected to be higher due to operational interruptions, validation activities, and the need to manually identify inactive or legacy accounts.

Overall, the process is labor-intensive, difficult to scale, and susceptible to manual errors. The primary inefficiencies stem from the lack of a shared identifier between source and destination systems and the requirement to manually reconcile records across multiple files before balances can be transferred.
