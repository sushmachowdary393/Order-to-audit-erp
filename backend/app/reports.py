import io
import csv
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from sqlalchemy import func
from sqlalchemy.orm import Session
from .models import (
    Item, ItemType, StockLedger, StockMovementType, Purchase, PurchaseLine,
    ProductionRun, ProductionConsumption, Invoice, InvoiceLine, Payment, Customer
)
from .services import (
    FACTORY_NAME, FACTORY_GSTIN, FACTORY_STATE_CODE,
    from_paise, from_paise_float, get_item_balance, get_weighted_avg_cost_paise
)

def build_gst_invoice_pdf(db: Session, invoice_id: int) -> bytes:
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).one()
    cust = inv.customer
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=28, leftMargin=28, topMargin=28, bottomMargin=28)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(f"<b>TAX INVOICE (GST COMPLIANT)</b>", styles["Title"]))
    elements.append(Paragraph(f"<b>{FACTORY_NAME}</b> | GSTIN: {FACTORY_GSTIN} | State: Tamil Nadu (33)", styles["Normal"]))
    elements.append(Spacer(1, 10))

    meta_data = [
        ["Invoice No:", inv.invoice_number, "Invoice Date:", str(inv.invoice_date)],
        ["Financial Year:", inv.financial_year, "Order Ref:", inv.order.order_number],
        ["Customer:", cust.name, "Customer GSTIN:", cust.gstin or "Unregistered"],
        ["Place of Supply:", f"{inv.place_of_supply_name} ({inv.place_of_supply_code})", "Supply Type:", "Inter-State (IGST)" if inv.is_interstate else "Intra-State (CGST+SGST)"],
    ]
    t_meta = Table(meta_data, colWidths=[95, 175, 95, 170])
    t_meta.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("BACKGROUND", (2, 0), (2, -1), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(t_meta)
    elements.append(Spacer(1, 14))

    rows = [["#", "Item Description", "HSN", "Qty (Pkts)", "Rate (Rs)", "Taxable (Rs)", "GST%", "CGST", "SGST", "IGST", "Total (Rs)"]]
    for idx, ln in enumerate(inv.lines, 1):
        rows.append([
            str(idx),
            ln.item.name,
            ln.hsn_code,
            f"{float(ln.qty_packets):.0f}",
            from_paise(ln.unit_price_paise),
            from_paise(ln.taxable_paise),
            f"{float(ln.gst_rate_pct):.1f}%",
            from_paise(ln.cgst_paise),
            from_paise(ln.sgst_paise),
            from_paise(ln.igst_paise),
            from_paise(ln.total_paise),
        ])
    rows.append([
        "", "TOTAL", "", "", "",
        from_paise(inv.taxable_paise), "",
        from_paise(inv.cgst_paise),
        from_paise(inv.sgst_paise),
        from_paise(inv.igst_paise),
        from_paise(inv.grand_total_paise)
    ])

    t_items = Table(rows, colWidths=[22, 128, 52, 46, 48, 58, 35, 42, 42, 42, 58])
    t_items.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("PADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(t_items)
    elements.append(Spacer(1, 14))

    bal = inv.grand_total_paise - inv.paid_paise
    elements.append(Paragraph(f"Paid Amount: Rs. {from_paise(inv.paid_paise)} | Balance Due: Rs. {from_paise(bal)} | Status: {inv.status.upper()}", styles["Normal"]))
    elements.append(Spacer(1, 20))
    elements.append(Paragraph("Authorised Signatory — Kaveri Traditional Foods Pvt Ltd", styles["Normal"]))

    doc.build(elements)
    return buf.getvalue()

def get_monthly_audit_reports(db: Session, start_date: Optional[date] = None, end_date: Optional[date] = None) -> dict:
    start_date = start_date or date.today().replace(day=1)
    end_date = end_date or date.today()

    # 1. Sales Register
    invoices = db.query(Invoice).filter(
        Invoice.invoice_date >= start_date,
        Invoice.invoice_date <= end_date
    ).order_by(Invoice.id).all()

    sales_register = []
    cust_summary = {}
    prod_summary = {}
    gst_summary = {
        "b2b_intra_tn": {"taxable": 0, "cgst": 0, "sgst": 0, "igst": 0, "total": 0, "count": 0},
        "b2b_inter_state": {"taxable": 0, "cgst": 0, "sgst": 0, "igst": 0, "total": 0, "count": 0},
    }

    for inv in invoices:
        if inv.status == "cancelled_credit_note":
            continue
        sales_register.append({
            "invoice_number": inv.invoice_number,
            "date": str(inv.invoice_date),
            "customer_name": inv.customer.name,
            "gstin": inv.customer.gstin or "URP",
            "place_of_supply": f"{inv.place_of_supply_name} ({inv.place_of_supply_code})",
            "taxable": from_paise_float(inv.taxable_paise),
            "cgst": from_paise_float(inv.cgst_paise),
            "sgst": from_paise_float(inv.sgst_paise),
            "igst": from_paise_float(inv.igst_paise),
            "grand_total": from_paise_float(inv.grand_total_paise),
            "paid": from_paise_float(inv.paid_paise),
            "outstanding": from_paise_float(inv.grand_total_paise - inv.paid_paise),
            "status": inv.status
        })
        bucket = "b2b_inter_state" if inv.is_interstate else "b2b_intra_tn"
        gst_summary[bucket]["taxable"] += inv.taxable_paise
        gst_summary[bucket]["cgst"] += inv.cgst_paise
        gst_summary[bucket]["sgst"] += inv.sgst_paise
        gst_summary[bucket]["igst"] += inv.igst_paise
        gst_summary[bucket]["total"] += inv.grand_total_paise
        gst_summary[bucket]["count"] += 1

        c_key = inv.customer.name
        cust_summary.setdefault(c_key, {"customer": c_key, "invoices": 0, "taxable": 0, "gst": 0, "total": 0, "paid": 0, "outstanding": 0})
        cust_summary[c_key]["invoices"] += 1
        cust_summary[c_key]["taxable"] += inv.taxable_paise
        cust_summary[c_key]["gst"] += (inv.cgst_paise + inv.sgst_paise + inv.igst_paise)
        cust_summary[c_key]["total"] += inv.grand_total_paise
        cust_summary[c_key]["paid"] += inv.paid_paise
        cust_summary[c_key]["outstanding"] += (inv.grand_total_paise - inv.paid_paise)

        for ln in inv.lines:
            p_key = ln.item.name
            prod_summary.setdefault(p_key, {"product": p_key, "hsn": ln.hsn_code, "qty_packets": Decimal("0"), "taxable": 0, "total": 0})
            prod_summary[p_key]["qty_packets"] += Decimal(str(ln.qty_packets))
            prod_summary[p_key]["taxable"] += ln.taxable_paise
            prod_summary[p_key]["total"] += ln.total_paise

    # 2. Purchase Register
    purchases = db.query(Purchase).filter(
        Purchase.purchase_date >= start_date,
        Purchase.purchase_date <= end_date
    ).all()
    purchase_register = []
    for p in purchases:
        for pl in p.lines:
            purchase_register.append({
                "purchase_number": p.purchase_number,
                "date": str(p.purchase_date),
                "supplier": p.supplier_name,
                "invoice_ref": p.invoice_ref or "",
                "item": pl.item.name,
                "qty": float(pl.qty),
                "unit": pl.unit,
                "rate": from_paise_float(pl.rate_paise),
                "taxable": from_paise_float(pl.taxable_paise),
                "gst": from_paise_float(pl.gst_paise),
                "total": from_paise_float(pl.total_paise),
            })

    # 3. Stock Summary & Stock Ledger
    items = db.query(Item).order_by(Item.item_type, Item.id).all()
    stock_summary = []
    for it in items:
        opening = db.query(func.coalesce(func.sum(StockLedger.qty_delta), 0)).filter(
            StockLedger.item_id == it.id,
            StockLedger.movement_type == StockMovementType.OPENING
        ).scalar()
        inflows = db.query(func.coalesce(func.sum(StockLedger.qty_delta), 0)).filter(
            StockLedger.item_id == it.id,
            StockLedger.qty_delta > 0,
            StockLedger.movement_type != StockMovementType.OPENING,
            StockLedger.txn_date >= start_date,
            StockLedger.txn_date <= end_date
        ).scalar()
        outflows = db.query(func.coalesce(func.sum(StockLedger.qty_delta), 0)).filter(
            StockLedger.item_id == it.id,
            StockLedger.qty_delta < 0,
            StockLedger.txn_date >= start_date,
            StockLedger.txn_date <= end_date
        ).scalar()
        closing = get_item_balance(db, it.id, end_date)
        wac_p = get_weighted_avg_cost_paise(db, it.id)
        val_p = int((closing * Decimal(wac_p)).quantize(Decimal("1")))
        stock_summary.append({
            "sku": it.sku,
            "name": it.name,
            "category": it.item_type.value,
            "unit": it.base_unit,
            "opening": float(opening or 0),
            "receipts_or_output": float(inflows or 0),
            "issues_or_sales": abs(float(outflows or 0)),
            "closing": float(closing),
            "wac_rate": from_paise_float(wac_p),
            "closing_value": from_paise_float(val_p),
            "low_stock": float(closing) <= float(it.reorder_level)
        })

    ledger_rows = db.query(StockLedger).filter(
        StockLedger.txn_date >= start_date,
        StockLedger.txn_date <= end_date
    ).order_by(StockLedger.id).all()
    stock_ledger = [{
        "id": l.id,
        "date": str(l.txn_date),
        "sku": l.item.sku,
        "item": l.item.name,
        "type": l.movement_type.value,
        "qty_delta": float(l.qty_delta),
        "unit": l.item.base_unit,
        "unit_cost": from_paise_float(l.unit_cost_paise),
        "source_ref": l.source_ref,
        "batch_no": l.batch_no or "",
        "notes": l.notes or ""
    } for l in ledger_rows]

    # 4. Production & Variance Report + Costing
    runs = db.query(ProductionRun).filter(
        ProductionRun.run_date >= start_date,
        ProductionRun.run_date <= end_date
    ).order_by(ProductionRun.id).all()
    production_report = []
    for r in runs:
        sp = r.finished_item.selling_price_paise
        margin_p = sp - r.cost_per_packet_paise
        margin_pct = round((margin_p / sp * 100), 2) if sp > 0 else 0
        production_report.append({
            "run_number": r.run_number,
            "date": str(r.run_date),
            "product": r.finished_item.name,
            "expected_packets": float(r.expected_output_packets),
            "actual_packets": float(r.actual_output_packets),
            "yield_variance_pct": float(r.yield_variance_pct),
            "yield_flagged": r.yield_flagged,
            "material_cost": from_paise_float(r.material_cost_paise),
            "labour_cost": from_paise_float(r.labour_cost_paise),
            "overhead_cost": from_paise_float(r.overhead_cost_paise),
            "total_cost": from_paise_float(r.total_cost_paise),
            "cost_per_packet": from_paise_float(r.cost_per_packet_paise),
            "selling_price": from_paise_float(sp),
            "margin_per_packet": from_paise_float(margin_p),
            "margin_pct": margin_pct,
            "consumptions": [{
                "item": c.item.name,
                "unit": c.item.base_unit,
                "planned": float(c.planned_qty),
                "actual_good": float(c.actual_good_qty),
                "wastage": float(c.damaged_wastage_qty),
                "total_consumed": float(c.total_consumed_qty),
                "variance_qty": float(c.variance_qty),
                "variance_pct": float(c.variance_pct),
                "flagged": c.variance_flagged,
                "rate": from_paise_float(c.unit_rate_paise),
                "cost": from_paise_float(c.total_cost_paise)
            } for c in r.consumptions]
        })

    # 5. Receivables Ageing & Collections
    today = date.today()
    receivables = []
    for inv in invoices:
        if inv.status == "cancelled_credit_note":
            continue
        out_p = inv.grand_total_paise - inv.paid_paise
        if out_p > 0:
            age_days = (today - inv.invoice_date).days
            bucket = "0-30 days" if age_days <= 30 else ("31-60 days" if age_days <= 60 else "60+ days")
            receivables.append({
                "customer": inv.customer.name,
                "invoice_number": inv.invoice_number,
                "invoice_date": str(inv.invoice_date),
                "invoice_total": from_paise_float(inv.grand_total_paise),
                "paid": from_paise_float(inv.paid_paise),
                "outstanding": from_paise_float(out_p),
                "age_days": age_days,
                "ageing_bucket": bucket
            })

    payments = db.query(Payment).filter(
        Payment.payment_date >= start_date,
        Payment.payment_date <= end_date
    ).all()
    collections = [{
        "receipt_number": p.receipt_number,
        "date": str(p.payment_date),
        "customer": p.customer.name,
        "invoice_number": p.invoice.invoice_number,
        "amount": from_paise_float(p.amount_paise),
        "mode": p.mode,
        "reference": p.reference_no or ""
    } for p in payments]

    return {
        "period": {"start": str(start_date), "end": str(end_date)},
        "sales_register": sales_register,
        "customer_wise_sales": [{
            **v,
            "taxable": from_paise_float(v["taxable"]),
            "gst": from_paise_float(v["gst"]),
            "total": from_paise_float(v["total"]),
            "paid": from_paise_float(v["paid"]),
            "outstanding": from_paise_float(v["outstanding"]),
        } for v in cust_summary.values()],
        "product_wise_sales": [{
            **v,
            "qty_packets": float(v["qty_packets"]),
            "taxable": from_paise_float(v["taxable"]),
            "total": from_paise_float(v["total"]),
        } for v in prod_summary.values()],
        "gst_summary": {
            k: {
                "invoices": val["count"],
                "taxable": from_paise_float(val["taxable"]),
                "cgst": from_paise_float(val["cgst"]),
                "sgst": from_paise_float(val["sgst"]),
                "igst": from_paise_float(val["igst"]),
                "total": from_paise_float(val["total"]),
            } for k, val in gst_summary.items()
        },
        "purchase_register": purchase_register,
        "stock_summary": stock_summary,
        "stock_ledger": stock_ledger,
        "production_report": production_report,
        "collections": collections,
        "receivables_ageing": receivables
    }

def export_audit_excel(reports: dict) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)

    def add_sheet(title: str, rows: list):
        ws = wb.create_sheet(title=title[:31])
        if not rows:
            ws.append(["No records for selected period"])
            return
        headers = list(rows[0].keys())
        ws.append([h.replace("_", " ").title() for h in headers])
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
        for r in rows:
            ws.append([str(r[h]) if isinstance(r[h], (list, dict)) else r[h] for h in headers])

    add_sheet("Sales Register", reports["sales_register"])
    gst_rows = [{"Supply_Type": k, **v} for k, v in reports["gst_summary"].items()]
    add_sheet("GST Summary GSTR1", gst_rows)
    add_sheet("Purchase Register", reports["purchase_register"])
    add_sheet("Stock Summary", reports["stock_summary"])
    add_sheet("Stock Ledger", reports["stock_ledger"])
    prod_flat = [{k: v for k, v in r.items() if k != "consumptions"} for r in reports["production_report"]]
    add_sheet("Production & Costing", prod_flat)
    add_sheet("Receivables Ageing", reports["receivables_ageing"])
    add_sheet("Collections", reports["collections"])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()

def export_tally_xml(reports: dict) -> str:
    vouchers = []
    for inv in reports["sales_register"]:
        vouchers.append(f"""  <TALLYMESSAGE xmlns:UDF="TallyUDF">
    <VOUCHER VCHTYPE="Sales" ACTION="Create">
      <DATE>{inv['date'].replace('-', '')}</DATE>
      <VOUCHERTYPENAME>Sales</VOUCHERTYPENAME>
      <VOUCHERNUMBER>{inv['invoice_number']}</VOUCHERNUMBER>
      <PARTYLEDGERNAME>{inv['customer_name']}</PARTYLEDGERNAME>
      <ALLLEDGERENTRIES.LIST>
        <LEDGERNAME>{inv['customer_name']}</LEDGERNAME>
        <ISDEEMEDPOSITIVE>Yes</ISDEEMEDPOSITIVE>
        <AMOUNT>-{inv['grand_total']:.2f}</AMOUNT>
      </ALLLEDGERENTRIES.LIST>
      <ALLLEDGERENTRIES.LIST>
        <LEDGERNAME>GST Sales</LEDGERNAME>
        <ISDEEMEDPOSITIVE>No</ISDEEMEDPOSITIVE>
        <AMOUNT>{inv['taxable']:.2f}</AMOUNT>
      </ALLLEDGERENTRIES.LIST>
    </VOUCHER>
  </TALLYMESSAGE>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ENVELOPE>
  <HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>
  <BODY><IMPORTDATA><REQUESTDATA>
{chr(10).join(vouchers)}
  </REQUESTDATA></IMPORTDATA></BODY>
</ENVELOPE>"""
