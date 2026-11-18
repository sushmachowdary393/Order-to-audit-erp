# Kaveri Foods — Order-to-Audit ERP System
**Centre for Digital Infrastructure, NIT Tiruchirappalli — Winter Internship 2026 Submission**

## 1. Tech Stack & Justification
- **Backend:** Python 3.11 + FastAPI + SQLAlchemy ORM + SQLite (drop-in compatible with PostgreSQL via `DATABASE_URL`). Chosen because FastAPI enforces strict schema validation while Python's native `Decimal` and integer-paisa arithmetic prevent floating-point rounding drift across GST, BOM consumption, and weighted-average costing.
- **Frontend:** Responsive Mobile-First Progressive Web App (HTML5 / CSS3 / Vanilla JS + `localStorage` offline queue). Chosen so field salesmen on low-bandwidth mobile connections can capture and auto-sync orders offline without heavy JS bundle overhead, while desktop users get dense multi-column audit tables.
- **Reports & Exports:** ReportLab (GST Tax Invoice PDF), OpenPyXL (8-tab Monthly Auditor Excel Pack), and Tally-compatible XML vouchers.

## 2. Quick Start (Single-Command Run)
### Option A: Docker Compose
```bash
docker compose up --build
```
Open `http://localhost:8000` in your browser.

### Option B: Local Python
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
Run automated benchmark verification tests:
```bash
cd backend && pytest -v
```

## 3. Test Logins (Role-Based Access)
All demo accounts use password `pass123` (or switch instantly via the top role selector):
- `salesman_a` — **Salesman A (Karthik)**: Mobile order entry, offline capture, own orders & customer sales.
- `salesman_b` — **Salesman B (Suresh)**: Mobile order entry for Karnataka distributor.
- `admin` — **Factory Admin (Meenakshi)**: Order stock check, approval, GST invoice PDF, dispatch, payment receipts, purchases.
- `production` — **Production Supervisor (Murugan)**: BOM-linked production runs, actual vs planned usage, wastage, overheads.
- `auditor` — **Accountant / Auditor (CA Raghavan)**: Read-only monthly registers, GSTR-1/3B summary, stock ledger, Excel/Tally exports.
- `owner` — **Owner (Anand)**: Executive KPI dashboard, variance alerts, cost/packet, receivables.

## 4. Scope Coverage (Section 6)
- **Must-Haves:** Role-based login (all 5 roles), Product/Customer/Raw-Material/BOM masters, mobile-friendly order entry & admin approval, GST PDF invoice (CGST+SGST & IGST), automated BOM production stock updates, planned vs actual variance tracking, immutable stock ledger & summary, Excel/CSV exports.
- **Should-Haves:** Purchase & supplier records, payments & receivables ageing, cost per packet with direct labour & overheads, GSTR-1/3B outward summary, 3% tolerance variance flags, Owner dashboard.
- **Stretch Goals Implemented:** Offline order capture with idempotent `client_offline_uuid` sync, batch & expiry tracking on stock movements, reorder level alerts, production batch planning from pending orders (`/api/production/planning`), and Tally XML voucher export.

## 5. Benchmark Verification Results (Section 5)
| Check | Expected | System Output | Status |
|---|---|---|---|
| Flour closing balance | 120 kg (`100 + 60 - 40`) | `120.0000 kg` | Exact Match |
| Cooking oil closing balance | 19.5 L (`30 - 10.5`) | `19.5000 L` | Exact Match |
| Pouches closing balance | 306 pcs (`500 - 188 - 6`) | `306.0000 pcs` | Exact Match |
| Cartons closing balance | 21 pcs (`30 - 9`) | `21.0000 pcs` | Exact Match |
| Finished goods after run | 238 packets (`50 + 188`) | `238.0000 pkts` | Exact Match |
| Finished goods after Retailer A dispatch | 88 packets (`238 - 150`) | `88.0000 pkts` | Exact Match |
| Yield variance | `-6%` (188 vs 200), flagged | `-6.00%` (`yield_flagged=True`) | Exact Match |
| Oil consumption variance | `+5%` (10.5 vs 10.0), flagged | `+5.00%` (`variance_flagged=True`) | Exact Match |
| Retailer A GST invoice (TN -> TN) | ₹7,500 + ₹187.50 CGST + ₹187.50 SGST = ₹7,875 | `₹7,500.00 + ₹187.50 + ₹187.50 = ₹7,875.00` | Exact Match |
| Retailer A outstanding after ₹4,000 payment | ₹3,875 | `₹3,875.00` | Exact Match |
| Distributor B order (120 pkts, KA) | Shortage 32 pkts flagged; IGST applies | Blocked with `shortage_qty=32`, regime `IGST (Inter-state)` | Exact Match |
| Cost per packet (with ₹1,200 labour + ₹600 gas/power) | Stated valuation & overhead rule | **₹31.14 / packet** (Selling price ₹50.00 → **37.72% gross margin**) | Explained Below |

### Costing & Valuation Explanation
1. **Inventory Valuation Method — Cumulative Weighted Average Cost (WAC):**
   - Flour opening stock is `100 kg @ ₹42.00 = ₹4,200.00`. Step 1 purchases `60 kg @ ₹45.00 = ₹2,700.00`.
   - Weighted Average Rate for Flour = `(₹4,200 + ₹2,700) / 160 kg = ₹43.125/kg`, rounded to nearest paisa (`₹43.13/kg`).
   - Other inputs have single rates: Oil `₹140.00/L`, Spice Mix `₹200.00/kg`, Pouches `₹2.50/pc`, Cartons `₹15.00/pc`.
2. **Direct Material Cost for Run 1:**
   - Flour: `40 kg × ₹43.13 = ₹1,725.20`
   - Cooking Oil: `10.5 L × ₹140.00 = ₹1,470.00`
   - Salt & Spice Mix: `1.2 kg × ₹200.00 = ₹240.00`
   - 200g Pouches (good + damaged): `(188 + 6) = 194 pcs × ₹2.50 = ₹485.00`
   - Cartons: `9 pcs × ₹15.00 = ₹135.00`
   - **Total Direct Material Cost = ₹4,055.20**
3. **Overhead Allocation Rule:**
   - Direct run labour (`₹1,200.00`) and run utilities/gas/power (`₹600.00`) are allocated directly to the production run and divided across **actual good saleable packets produced (`188 packets`)** so wastage/yield loss is absorbed into unit cost:
   - Total Run Cost = `₹4,055.20 + ₹1,200.00 + ₹600.00 = ₹5,855.20`
   - **Cost per Packet** = `₹5,855.20 / 188 packets = ₹31.1446...` → **₹31.14 / packet** (3114 paise).

## 6. Assumptions & Known Gaps
- **Assumptions:** (1) Factory is registered in Tamil Nadu (State Code `33`), so TN customers attract `2.5% CGST + 2.5% SGST` while out-of-state customers (Karnataka `29`) attract `5% IGST`. (2) Damaged pouches (`6 pcs`) are charged to production run material cost rather than written off separately. (3) Invoices are never deleted; posted invoices are reversed via Credit Notes (`CN/...`) with automatic ledger stock restoration.
- **Known Gaps:** Full e-Invoice IRN cryptographic signing with NIC sandbox and multi-godown bin transfers are out of scope for this single-factory prototype.
