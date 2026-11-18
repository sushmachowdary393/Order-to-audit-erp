# Design Note: Order-to-Audit System for a Small Food Manufacturer
**Author:** Internship Applicant — Centre for Digital Infrastructure, NIT Tiruchirappalli

## 1. Core Architecture & Entity-Relationship Model
The system unifies the **Sales Loop** and **Production Loop** around an **append-only Stock Ledger (`stock_ledger`)**. No screen ever directly overwrites an item's stock quantity; instead, current stock is always derived as `SUM(qty_delta)` grouped by `item_id`, guaranteeing 100% reconciliation between physical stock movements and source documents.

```
+---------------+       +------------------+       +---------------------+
|   customers   |------>|   sales_orders   |------>|      invoices       |
+---------------+       +------------------+       +---------------------+
                               |                             |
                               v                             v
                        +------------------+       +---------------------+
                        | sales_order_lines|       |      payments       |
                        +------------------+       +---------------------+
                                                             |
+---------------+       +------------------+                 | (SALES_DISPATCH)
|     items     |<------|    bom_lines     |                 v
+---------------+       +------------------+       +---------------------+
   ^        ^                    ^                 |    stock_ledger     |
   |        |                    |                 | (Append-Only Ledger)|
   |        +--------------------+                 +---------------------+
   |                             |                   ^       ^       ^
   |                    +------------------+         |       |       |
   +--------------------|  production_runs |---------+       |       |
                        +------------------+ (ISSUE/OUTPUT)  |       |
                                 ^                           |       |
                        +------------------+                 |       |
                        |  purchase_lines  |-----------------+       |
                        +------------------+   (PURCHASE)            |
                                                                     |
                        +------------------+                         |
                        | opening_balances |-------------------------+
                        +------------------+   (OPENING)
```

### Key Relational Tables
1. **`items`**: Stores Raw Materials (`kg`, `L`), Packaging (`piece`), and Finished Goods (`packet`), along with `pack_size_grams`, `packets_per_carton`, `hsn_code`, `gst_rate_pct`, and `selling_price_paise`.
2. **`bom_headers` & `bom_lines`**: Defines standard recipe quantities per batch, expected packet yield, and variance tolerance (`3.00%`).
3. **`production_runs` & `production_consumptions`**: Records batch multiplier, actual good packets, planned vs. actual component usage, damaged/scrap quantities, variance percentages, and run overheads.
4. **`sales_orders` → `invoices` → `payments`**: Captures mobile field orders (with `client_offline_uuid` for idempotent offline sync), validates finished-goods stock before approval, computes CGST/SGST vs. IGST by `place_of_supply_code`, deducts stock upon dispatch, and tracks partial payments.
5. **`audit_logs`**: Immutable trail recording user, timestamp, action, and before/after values for every critical state change. Posted invoices cannot be deleted; cancellation issues a linked Credit Note (`CN/...`).

## 2. BOM Consumption, Unit Conversion & Variance Logic
- **Unit Conversion Engine (`convert_unit`)**: Converts deterministically using exact `Decimal` factors (`1 kg = 1000 g`, `1 L = 1000 ml`, `1 carton = packets_per_carton × packets`). Adding a new pack size (e.g., *Murukku 500 g* sharing the same dough recipe at `2.5×` flour/oil/spice per packet) requires only inserting a new `Item` and `BOMHeader` scaled by pack weight—zero code changes.
- **Consumption & Wastage Split**: Each `ProductionConsumption` row tracks `actual_good_qty` (incorporated into output) and `damaged_wastage_qty` (e.g., 6 torn pouches). Both post negative `qty_delta` entries to `stock_ledger` (`PRODUCTION_ISSUE` and `PRODUCTION_WASTAGE`), while `actual_output_packets` posts a positive `PRODUCTION_OUTPUT` entry.
- **Variance Flagging**:
  - $	ext{Consumption Variance \%} = rac{	ext{Total Consumed} - 	ext{Planned BOM Qty}}{	ext{Planned BOM Qty}} 	imes 100$
  - $	ext{Yield Variance \%} = rac{	ext{Actual Output} - 	ext{Expected Yield}}{	ext{Expected Yield}} 	imes 100$
  - Any metric where $|	ext{Variance \%}| > 	ext{tolerance\_pct}$ (`3.0%`) sets `flagged = True` and surfaces alerts on the Production and Owner dashboards.

## 3. Financial Precision & Costing Methodology
- **Integer-Paisa Arithmetic**: All monetary fields (`rate_paise`, `taxable_paise`, `cgst_paise`, `sgst_paise`, `igst_paise`, `grand_total_paise`) are stored as 64-bit integers (`₹1 = 100 paise`), and intermediate multiplications use `Decimal` with `ROUND_HALF_UP`. This eliminates IEEE-754 binary float drift on GST splits and multi-line invoices.
- **Inventory Valuation — Moving Weighted Average Cost (WAC)**:
  $$	ext{WAC}_{	ext{paise}} = 	ext{Round}\left(rac{\sum (	ext{Inflow Qty}_i 	imes 	ext{Inflow Unit Cost}_i)}{\sum 	ext{Inflow Qty}_i}ight)$$
  WAC smooths raw-material price fluctuations (e.g., flour moving from ₹42/kg opening to ₹45/kg new purchase → ₹43.13/kg) without requiring manual lot-picking on the shop floor, while still recording `batch_no` and `expiry_date` on ledger rows for food safety traceability.
- **Unit Cost per Packet**:
  $$	ext{Cost per Packet} = rac{\sum (	ext{Total Consumed}_j 	imes 	ext{WAC}_j) + 	ext{Run Labour} + 	ext{Run Gas/Power}}{	ext{Actual Good Packets Produced}}$$
  Dividing total batch cost by **actual good packets** (188) rather than theoretical yield (200) ensures yield losses and packaging scrap are transparently reflected in unit margin (`₹50.00 - ₹31.14 = ₹18.86/pkt`, or `37.72%`).
