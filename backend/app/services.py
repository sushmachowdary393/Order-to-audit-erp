from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session
from .models import (
    User, UserRole, Customer, Supplier, Item, ItemType, BOMHeader, BOMLine,
    Purchase, PurchaseLine, ProductionRun, ProductionConsumption,
    SalesOrder, SalesOrderLine, OrderStatus, Invoice, InvoiceLine,
    Payment, StockLedger, StockMovementType, AuditLog
)

FACTORY_STATE_CODE = "33"  # Tamil Nadu
FACTORY_GSTIN = "33AABCS1429B1Z5"
FACTORY_NAME = "Kaveri Traditional Foods Pvt Ltd, Trichy"

def to_paise(rupees: Decimal | float | int | str) -> int:
    d = Decimal(str(rupees))
    return int((d * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

def from_paise(paise: int) -> str:
    return f"{(Decimal(paise) / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"

def from_paise_float(paise: int) -> float:
    return float((Decimal(paise) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

def dec(val) -> Decimal:
    return Decimal(str(val)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

def log_audit(db: Session, user: Optional[User], action: str, entity_type: str, entity_id: str, details: str):
    db.add(AuditLog(
        user_id=user.id if user else None,
        username=user.username if user else "system",
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=details
    ))

# --- UNIT CONVERSION ENGINE ---
UNIT_FACTORS = {
    ("kg", "g"): Decimal("1000"),
    ("g", "kg"): Decimal("0.001"),
    ("L", "ml"): Decimal("1000"),
    ("ml", "L"): Decimal("0.001"),
    ("litre", "L"): Decimal("1"),
    ("L", "litre"): Decimal("1"),
}

def convert_unit(qty: Decimal, from_u: str, to_u: str, packets_per_carton: Optional[int] = None) -> Decimal:
    if from_u == to_u:
        return qty
    if (from_u, to_u) in UNIT_FACTORS:
        return (qty * UNIT_FACTORS[(from_u, to_u)]).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if from_u == "carton" and to_u == "packet" and packets_per_carton:
        return (qty * Decimal(packets_per_carton)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    if from_u == "packet" and to_u == "carton" and packets_per_carton:
        return (qty / Decimal(packets_per_carton)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    raise ValueError(f"Unsupported unit conversion: {from_u} -> {to_u}")

# --- LEDGER-DERIVED STOCK & WEIGHTED AVERAGE COSTING ---
def get_item_balance(db: Session, item_id: int, as_of_date: Optional[date] = None) -> Decimal:
    q = db.query(func.coalesce(func.sum(StockLedger.qty_delta), 0)).filter(StockLedger.item_id == item_id)
    if as_of_date:
        q = q.filter(StockLedger.txn_date <= as_of_date)
    val = q.scalar()
    return Decimal(str(val or 0)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

def get_weighted_avg_cost_paise(db: Session, item_id: int) -> int:
    """
    Moving / Cumulative Weighted Average Cost (WAC) across all positive stock inflows
    (OPENING + PURCHASE + PRODUCTION_OUTPUT).
    """
    inflows = db.query(StockLedger).filter(
        StockLedger.item_id == item_id,
        StockLedger.qty_delta > 0,
        StockLedger.movement_type.in_([
            StockMovementType.OPENING,
            StockMovementType.PURCHASE,
            StockMovementType.PRODUCTION_OUTPUT
        ])
    ).all()
    total_qty = Decimal("0")
    total_val_paise = Decimal("0")
    for row in inflows:
        q = Decimal(str(row.qty_delta))
        total_qty += q
        total_val_paise += q * Decimal(row.unit_cost_paise)
    if total_qty <= 0:
        item = db.query(Item).filter(Item.id == item_id).first()
        return item.standard_rate_paise if item else 0
    return int((total_val_paise / total_qty).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

# --- PURCHASE RECORDING ---
def record_purchase(
    db: Session,
    user: User,
    supplier_name: str,
    invoice_ref: str,
    purchase_date: date,
    items_in: List[dict]
) -> Purchase:
    count = db.query(Purchase).count() + 1
    p_num = f"PUR/26-27/{count:04d}"
    purchase = Purchase(
        purchase_number=p_num,
        supplier_name=supplier_name,
        invoice_ref=invoice_ref,
        purchase_date=purchase_date,
        created_by_id=user.id
    )
    db.add(purchase)
    db.flush()

    for line in items_in:
        item = db.query(Item).filter(Item.id == line["item_id"]).one()
        qty = dec(line["qty"])
        rate_paise = int(line["rate_paise"])
        gst_pct = Decimal(str(line.get("gst_rate_pct", item.gst_rate_pct)))
        taxable = int((qty * Decimal(rate_paise)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        gst_amt = int((Decimal(taxable) * gst_pct / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total = taxable + gst_amt

        pl = PurchaseLine(
            purchase_id=purchase.id,
            item_id=item.id,
            batch_no=line.get("batch_no") or f"BATCH-{purchase.id}-{item.sku}",
            expiry_date=line.get("expiry_date"),
            qty=qty,
            unit=item.base_unit,
            rate_paise=rate_paise,
            gst_rate_pct=gst_pct,
            taxable_paise=taxable,
            gst_paise=gst_amt,
            total_paise=total
        )
        db.add(pl)

        # Stock Ledger inflow
        db.add(StockLedger(
            txn_date=purchase_date,
            item_id=item.id,
            movement_type=StockMovementType.PURCHASE,
            qty_delta=qty,
            unit_cost_paise=rate_paise,
            source_type="PURCHASE",
            source_id=purchase.id,
            source_ref=p_num,
            batch_no=pl.batch_no,
            expiry_date=pl.expiry_date,
            notes=f"Purchase from {supplier_name} ({invoice_ref})",
            created_by_id=user.id
        ))

    log_audit(db, user, "CREATE_PURCHASE", "Purchase", p_num, f"Recorded purchase {p_num} from {supplier_name}")
    db.commit()
    db.refresh(purchase)
    return purchase

# --- PRODUCTION RUN & BOM VARIANCE ENGINE ---
def record_production_run(
    db: Session,
    user: User,
    finished_item_id: int,
    batch_multiplier: Decimal,
    actual_output_packets: Decimal,
    consumptions_in: List[dict],
    labour_cost_paise: int = 0,
    overhead_cost_paise: int = 0,
    run_date: Optional[date] = None
) -> ProductionRun:
    run_date = run_date or date.today()
    bom = db.query(BOMHeader).filter(BOMHeader.finished_item_id == finished_item_id).one()
    finished_item = db.query(Item).filter(Item.id == finished_item_id).one()
    mult = dec(batch_multiplier)
    expected_out = (Decimal(str(bom.expected_yield_packets)) * mult).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    actual_out = dec(actual_output_packets)

    # Validate stock availability before posting
    for c in consumptions_in:
        c_item = db.query(Item).filter(Item.id == c["item_id"]).one()
        tot_needed = dec(c["actual_good_qty"]) + dec(c.get("damaged_wastage_qty", 0))
        avail = get_item_balance(db, c_item.id)
        if avail < tot_needed:
            raise ValueError(f"Insufficient stock for {c_item.name}: available {avail} {c_item.base_unit}, required {tot_needed}")

    yield_var_pct = (((actual_out - expected_out) / expected_out) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    yield_flagged = abs(yield_var_pct) > Decimal(str(bom.tolerance_pct))

    count = db.query(ProductionRun).count() + 1
    run_num = f"PRD/26-27/{count:04d}"
    batch_code = f"FG-{run_date.strftime('%y%m%d')}-{count:03d}"

    run = ProductionRun(
        run_number=run_num,
        bom_id=bom.id,
        finished_item_id=finished_item.id,
        batch_multiplier=mult,
        run_date=run_date,
        expected_output_packets=expected_out,
        actual_output_packets=actual_out,
        yield_variance_pct=yield_var_pct,
        yield_flagged=yield_flagged,
        labour_cost_paise=labour_cost_paise,
        overhead_cost_paise=overhead_cost_paise,
        batch_code=batch_code,
        expiry_date=run_date + timedelta(days=90),
        created_by_id=user.id
    )
    db.add(run)
    db.flush()

    bom_map = {line.component_item_id: line for line in bom.lines}
    total_mat_cost_paise = 0

    for c in consumptions_in:
        comp_id = c["item_id"]
        comp_item = db.query(Item).filter(Item.id == comp_id).one()
        bom_line = bom_map.get(comp_id)
        planned = (Decimal(str(bom_line.qty_per_batch)) * mult).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) if bom_line else Decimal("0")
        good_qty = dec(c["actual_good_qty"])
        dmg_qty = dec(c.get("damaged_wastage_qty", 0))
        tot_consumed = good_qty + dmg_qty

        var_qty = (tot_consumed - planned).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        var_pct = (((tot_consumed - planned) / planned) * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if planned > 0 else Decimal("0.00")
        flagged = abs(var_pct) > Decimal(str(bom.tolerance_pct))

        wac_paise = get_weighted_avg_cost_paise(db, comp_id)
        line_cost_paise = int((tot_consumed * Decimal(wac_paise)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        total_mat_cost_paise += line_cost_paise

        db.add(ProductionConsumption(
            run_id=run.id,
            item_id=comp_id,
            planned_qty=planned,
            actual_good_qty=good_qty,
            damaged_wastage_qty=dmg_qty,
            total_consumed_qty=tot_consumed,
            variance_qty=var_qty,
            variance_pct=var_pct,
            variance_flagged=flagged,
            unit_rate_paise=wac_paise,
            total_cost_paise=line_cost_paise
        ))

        if good_qty > 0:
            db.add(StockLedger(
                txn_date=run_date,
                item_id=comp_id,
                movement_type=StockMovementType.PRODUCTION_ISSUE,
                qty_delta=-good_qty,
                unit_cost_paise=wac_paise,
                source_type="PRODUCTION_RUN",
                source_id=run.id,
                source_ref=run_num,
                notes=f"Issued to {run_num} ({finished_item.name})",
                created_by_id=user.id
            ))
        if dmg_qty > 0:
            db.add(StockLedger(
                txn_date=run_date,
                item_id=comp_id,
                movement_type=StockMovementType.PRODUCTION_WASTAGE,
                qty_delta=-dmg_qty,
                unit_cost_paise=wac_paise,
                source_type="PRODUCTION_RUN",
                source_id=run.id,
                source_ref=run_num,
                notes=f"Damaged/scrap in {run_num}",
                created_by_id=user.id
            ))

    total_cost_paise = total_mat_cost_paise + labour_cost_paise + overhead_cost_paise
    cost_per_pkt_paise = int((Decimal(total_cost_paise) / actual_out).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if actual_out > 0 else 0

    run.material_cost_paise = total_mat_cost_paise
    run.total_cost_paise = total_cost_paise
    run.cost_per_packet_paise = cost_per_pkt_paise

    # Finished goods inflow
    db.add(StockLedger(
        txn_date=run_date,
        item_id=finished_item.id,
        movement_type=StockMovementType.PRODUCTION_OUTPUT,
        qty_delta=actual_out,
        unit_cost_paise=cost_per_pkt_paise,
        source_type="PRODUCTION_RUN",
        source_id=run.id,
        source_ref=run_num,
        batch_no=batch_code,
        expiry_date=run.expiry_date,
        notes=f"Produced {actual_out} packets (expected {expected_out})",
        created_by_id=user.id
    ))

    log_audit(db, user, "POST_PRODUCTION_RUN", "ProductionRun", run_num, f"Posted {run_num}: actual={actual_out}, cost/pkt={from_paise(cost_per_pkt_paise)}")
    db.commit()
    db.refresh(run)
    return run

def update_run_overheads(db: Session, user: User, run_id: int, labour_cost_paise: int, overhead_cost_paise: int) -> ProductionRun:
    run = db.query(ProductionRun).filter(ProductionRun.id == run_id).one()
    old_info = f"labour={from_paise(run.labour_cost_paise)}, overhead={from_paise(run.overhead_cost_paise)}"
    run.labour_cost_paise = labour_cost_paise
    run.overhead_cost_paise = overhead_cost_paise
    run.total_cost_paise = run.material_cost_paise + labour_cost_paise + overhead_cost_paise
    run.cost_per_packet_paise = int((Decimal(run.total_cost_paise) / Decimal(str(run.actual_output_packets))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # Update unit_cost_paise on the finished goods ledger entry for this run
    fg_entry = db.query(StockLedger).filter(
        StockLedger.source_type == "PRODUCTION_RUN",
        StockLedger.source_id == run.id,
        StockLedger.movement_type == StockMovementType.PRODUCTION_OUTPUT
    ).first()
    if fg_entry:
        fg_entry.unit_cost_paise = run.cost_per_packet_paise

    log_audit(db, user, "UPDATE_RUN_OVERHEADS", "ProductionRun", run.run_number, f"Updated overheads ({old_info} -> labour={from_paise(labour_cost_paise)}, overhead={from_paise(overhead_cost_paise)})")
    db.commit()
    db.refresh(run)
    return run

# --- SALES ORDER, STOCK CHECK, GST INVOICE & DISPATCH ENGINE ---
def create_sales_order(
    db: Session,
    salesman: User,
    customer_id: int,
    lines_in: List[dict],
    notes: str = "",
    client_offline_uuid: Optional[str] = None,
    gps_lat: Optional[str] = None,
    gps_lng: Optional[str] = None
) -> SalesOrder:
    if client_offline_uuid:
        existing = db.query(SalesOrder).filter(SalesOrder.client_offline_uuid == client_offline_uuid).first()
        if existing:
            return existing

    count = db.query(SalesOrder).count() + 1
    ord_num = f"ORD/26-27/{count:04d}"
    order = SalesOrder(
        order_number=ord_num,
        client_offline_uuid=client_offline_uuid,
        customer_id=customer_id,
        salesman_id=salesman.id,
        status=OrderStatus.SUBMITTED,
        notes=notes,
        gps_lat=gps_lat,
        gps_lng=gps_lng
    )
    db.add(order)
    db.flush()

    for ln in lines_in:
        item = db.query(Item).filter(Item.id == ln["item_id"]).one()
        price_paise = ln.get("unit_price_paise") if ln.get("unit_price_paise") is not None else item.selling_price_paise
        db.add(SalesOrderLine(
            order_id=order.id,
            item_id=item.id,
            qty_packets=dec(ln["qty_packets"]),
            unit_price_paise=int(price_paise)
        ))

    log_audit(db, salesman, "SUBMIT_ORDER", "SalesOrder", ord_num, f"Submitted order {ord_num}")
    db.commit()
    db.refresh(order)
    return order

def check_order_stock(db: Session, order: SalesOrder) -> dict:
    customer = db.query(Customer).filter(Customer.id == order.customer_id).one()
    is_interstate = customer.state_code != FACTORY_STATE_CODE
    line_checks = []
    all_sufficient = True
    for ln in order.lines:
        avail = get_item_balance(db, ln.item_id)
        req = Decimal(str(ln.qty_packets))
        shortage = max(Decimal("0"), req - avail)
        if shortage > 0:
            all_sufficient = False
        line_checks.append({
            "item_id": ln.item_id,
            "item_name": ln.item.name,
            "requested_qty": float(req),
            "available_qty": float(avail),
            "shortage_qty": float(shortage),
            "sufficient": shortage == 0
        })
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "customer_name": customer.name,
        "place_of_supply": f"{customer.state_name} ({customer.state_code})",
        "tax_regime": "IGST (Inter-state)" if is_interstate else "CGST + SGST (Intra-state Tamil Nadu)",
        "all_sufficient": all_sufficient,
        "lines": line_checks
    }

def approve_and_invoice_order(
    db: Session,
    admin: User,
    order_id: int,
    edited_lines: Optional[List[dict]] = None,
    allow_backorder_override: bool = False
) -> Invoice:
    order = db.query(SalesOrder).filter(SalesOrder.id == order_id).one()
    if order.status in (OrderStatus.INVOICED, OrderStatus.DISPATCHED):
        raise ValueError(f"Order {order.order_number} is already {order.status.value}")

    if edited_lines:
        # Replace lines if admin adjusted qty/price
        db.query(SalesOrderLine).filter(SalesOrderLine.order_id == order.id).delete()
        db.flush()
        for ln in edited_lines:
            db.add(SalesOrderLine(
                order_id=order.id,
                item_id=ln["item_id"],
                qty_packets=dec(ln["qty_packets"]),
                unit_price_paise=int(ln["unit_price_paise"])
            ))
        db.flush()
        db.refresh(order)

    stock_status = check_order_stock(db, order)
    if not stock_status["all_sufficient"] and not allow_backorder_override:
        shortages = [f"{l['item_name']}: short by {int(l['shortage_qty'])} packets (avail {int(l['available_qty'])}, req {int(l['requested_qty'])})" for l in stock_status["lines"] if not l["sufficient"]]
        raise ValueError("Insufficient finished goods stock: " + "; ".join(shortages))

    customer = db.query(Customer).filter(Customer.id == order.customer_id).one()
    is_interstate = customer.state_code != FACTORY_STATE_CODE

    inv_count = db.query(Invoice).count() + 1
    inv_num = f"FY26-27/INV/{inv_count:04d}"

    invoice = Invoice(
        invoice_number=inv_num,
        financial_year="2026-27",
        order_id=order.id,
        customer_id=customer.id,
        invoice_date=date.today(),
        place_of_supply_code=customer.state_code,
        place_of_supply_name=customer.state_name,
        is_interstate=is_interstate,
        taxable_paise=0,
        cgst_paise=0,
        sgst_paise=0,
        igst_paise=0,
        grand_total_paise=0,
        status="invoiced",
        created_by_id=admin.id
    )
    db.add(invoice)
    db.flush()

    tot_taxable = 0
    tot_cgst = 0
    tot_sgst = 0
    tot_igst = 0

    for ln in order.lines:
        item = ln.item
        qty = Decimal(str(ln.qty_packets))
        taxable = int((qty * Decimal(ln.unit_price_paise)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        gst_rate = Decimal(str(item.gst_rate_pct))
        if is_interstate:
            igst = int((Decimal(taxable) * gst_rate / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            cgst = 0
            sgst = 0
        else:
            half_rate = gst_rate / Decimal("2")
            cgst = int((Decimal(taxable) * half_rate / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            sgst = int((Decimal(taxable) * half_rate / Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            igst = 0

        line_tot = taxable + cgst + sgst + igst
        tot_taxable += taxable
        tot_cgst += cgst
        tot_sgst += sgst
        tot_igst += igst

        db.add(InvoiceLine(
            invoice_id=invoice.id,
            item_id=item.id,
            hsn_code=item.hsn_code,
            qty_packets=qty,
            unit_price_paise=ln.unit_price_paise,
            taxable_paise=taxable,
            gst_rate_pct=gst_rate,
            cgst_paise=cgst,
            sgst_paise=sgst,
            igst_paise=igst,
            total_paise=line_tot
        ))

    invoice.taxable_paise = tot_taxable
    invoice.cgst_paise = tot_cgst
    invoice.sgst_paise = tot_sgst
    invoice.igst_paise = tot_igst
    invoice.grand_total_paise = tot_taxable + tot_cgst + tot_sgst + tot_igst

    order.status = OrderStatus.INVOICED
    log_audit(db, admin, "APPROVE_AND_INVOICE", "Invoice", inv_num, f"Approved {order.order_number} -> {inv_num}, Total={from_paise(invoice.grand_total_paise)}")
    db.commit()
    db.refresh(invoice)
    return invoice

def dispatch_invoice(db: Session, admin: User, invoice_id: int) -> Invoice:
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).one()
    if invoice.status == "dispatched":
        return invoice
    if invoice.status == "cancelled_credit_note":
        raise ValueError("Cannot dispatch a cancelled invoice")

    for ln in invoice.lines:
        avail = get_item_balance(db, ln.item_id)
        req = Decimal(str(ln.qty_packets))
        if avail < req:
            raise ValueError(f"Cannot dispatch {invoice.invoice_number}: {ln.item.name} available {avail}, required {req}")

    for ln in invoice.lines:
        wac = get_weighted_avg_cost_paise(db, ln.item_id)
        db.add(StockLedger(
            txn_date=date.today(),
            item_id=ln.item_id,
            movement_type=StockMovementType.SALES_DISPATCH,
            qty_delta=-Decimal(str(ln.qty_packets)),
            unit_cost_paise=wac,
            source_type="INVOICE",
            source_id=invoice.id,
            source_ref=invoice.invoice_number,
            notes=f"Dispatched to {invoice.customer.name}",
            created_by_id=admin.id
        ))

    invoice.status = "dispatched"
    invoice.dispatched_at = datetime.utcnow()
    invoice.order.status = OrderStatus.DISPATCHED
    log_audit(db, admin, "DISPATCH_INVOICE", "Invoice", invoice.invoice_number, f"Dispatched {invoice.invoice_number}")
    db.commit()
    db.refresh(invoice)
    return invoice

def cancel_invoice_with_credit_note(db: Session, admin: User, invoice_id: int, reason: str) -> Invoice:
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).one()
    if invoice.status == "cancelled_credit_note":
        raise ValueError("Invoice already cancelled")
    cn_num = f"CN/{invoice.invoice_number}"
    if invoice.status == "dispatched":
        for ln in invoice.lines:
            wac = get_weighted_avg_cost_paise(db, ln.item_id)
            db.add(StockLedger(
                txn_date=date.today(),
                item_id=ln.item_id,
                movement_type=StockMovementType.ADJUSTMENT,
                qty_delta=Decimal(str(ln.qty_packets)),
                unit_cost_paise=wac,
                source_type="CREDIT_NOTE",
                source_id=invoice.id,
                source_ref=cn_num,
                notes=f"Stock reversal on cancellation: {reason}",
                created_by_id=admin.id
            ))
    invoice.status = "cancelled_credit_note"
    invoice.credit_note_number = cn_num
    log_audit(db, admin, "CANCEL_INVOICE_CN", "Invoice", invoice.invoice_number, f"Issued {cn_num}: {reason}")
    db.commit()
    db.refresh(invoice)
    return invoice

def record_payment(
    db: Session,
    admin: User,
    invoice_id: int,
    amount_paise: int,
    mode: str = "NEFT/UPI",
    reference_no: str = "",
    payment_date: Optional[date] = None
) -> Payment:
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).one()
    if amount_paise <= 0:
        raise ValueError("Payment amount must be positive")
    outstanding = invoice.grand_total_paise - invoice.paid_paise
    if amount_paise > outstanding:
        raise ValueError(f"Payment {from_paise(amount_paise)} exceeds invoice outstanding {from_paise(outstanding)}")

    count = db.query(Payment).count() + 1
    rcpt_num = f"RCPT/26-27/{count:04d}"
    pmt = Payment(
        receipt_number=rcpt_num,
        invoice_id=invoice.id,
        customer_id=invoice.customer_id,
        payment_date=payment_date or date.today(),
        amount_paise=amount_paise,
        mode=mode,
        reference_no=reference_no,
        recorded_by_id=admin.id
    )
    db.add(pmt)
    invoice.paid_paise += amount_paise
    log_audit(db, admin, "RECORD_PAYMENT", "Payment", rcpt_num, f"Received {from_paise(amount_paise)} against {invoice.invoice_number}")
    db.commit()
    db.refresh(pmt)
    return pmt
