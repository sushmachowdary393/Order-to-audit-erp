import os
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from .models import (
    Base, User, UserRole, Customer, Item, ItemType, BOMHeader, BOMLine,
    Purchase, ProductionRun, SalesOrder, Invoice, Payment, StockLedger, AuditLog
)
from .services import (
    to_paise, from_paise, from_paise_float, get_item_balance, get_weighted_avg_cost_paise,
    record_purchase, record_production_run, update_run_overheads,
    create_sales_order, check_order_stock, approve_and_invoice_order,
    dispatch_invoice, cancel_invoice_with_credit_note, record_payment
)
from .seed import reset_and_seed_benchmark, hash_pw
from .reports import build_gst_invoice_pdf, get_monthly_audit_reports, export_audit_excel, export_tally_xml

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./kaveri_erp.db")
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Kaveri Order-to-Audit ERP", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Ensure seed data exists on cold start
with SessionLocal() as db:
    if db.query(User).count() == 0:
        reset_and_seed_benchmark(db)

def get_current_user(x_username: Optional[str] = Header(default="admin"), db: Session = Depends(get_db)) -> User:
    user = db.query(User).filter(User.username == x_username, User.is_active == True).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or inactive user session")
    return user

def require_roles(*roles: UserRole):
    def checker(user: User = Depends(get_current_user)):
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"Role '{user.role.value}' is not authorized for this action")
        return user
    return checker

# --- SCHEMAS ---
class LoginReq(BaseModel):
    username: str
    password: str = "pass123"

class PurchaseLineIn(BaseModel):
    item_id: int
    qty: float
    rate_rupees: float
    batch_no: Optional[str] = None
    expiry_date: Optional[date] = None

class PurchaseReq(BaseModel):
    supplier_name: str
    invoice_ref: str = ""
    purchase_date: Optional[date] = None
    items: List[PurchaseLineIn]

class ConsumptionIn(BaseModel):
    item_id: int
    actual_good_qty: float
    damaged_wastage_qty: float = 0

class ProductionRunReq(BaseModel):
    finished_item_id: int
    batch_multiplier: float = 1.0
    actual_output_packets: float
    consumptions: List[ConsumptionIn]
    labour_cost_rupees: float = 0
    overhead_cost_rupees: float = 0
    run_date: Optional[date] = None

class OverheadUpdateReq(BaseModel):
    labour_cost_rupees: float
    overhead_cost_rupees: float

class OrderLineIn(BaseModel):
    item_id: int
    qty_packets: float
    unit_price_rupees: Optional[float] = None

class OrderReq(BaseModel):
    customer_id: int
    lines: List[OrderLineIn]
    notes: str = ""
    client_offline_uuid: Optional[str] = None
    gps_lat: Optional[str] = None
    gps_lng: Optional[str] = None

class ApproveOrderReq(BaseModel):
    edited_lines: Optional[List[OrderLineIn]] = None
    allow_backorder_override: bool = False

class PaymentReq(BaseModel):
    invoice_id: int
    amount_rupees: float
    mode: str = "NEFT/UPI"
    reference_no: str = ""
    payment_date: Optional[date] = None

class CancelInvoiceReq(BaseModel):
    reason: str

# --- AUTH & MASTER ENDPOINTS ---
@app.post("/api/auth/login")
def login(req: LoginReq, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or user.password_hash != hash_pw(req.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    return {
        "username": user.username,
        "full_name": user.full_name,
        "role": user.role.value
    }

@app.post("/api/system/reset-benchmark")
def reset_benchmark(db: Session = Depends(get_db)):
    reset_and_seed_benchmark(db)
    return {"status": "ok", "message": "Database reset to Section 5 Benchmark Master Data"}

@app.get("/api/masters")
def get_masters(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = db.query(Item).filter(Item.is_active == True).all()
    customers = db.query(Customer).all()
    if user.role == UserRole.SALESMAN:
        # Salesmen see assigned customers (or all if unallocated)
        assigned = [c for c in customers if c.assigned_salesman_id == user.id]
        if assigned:
            customers = assigned
    boms = db.query(BOMHeader).all()
    return {
        "items": [{
            "id": i.id,
            "sku": i.sku,
            "name": i.name,
            "item_type": i.item_type.value,
            "base_unit": i.base_unit,
            "pack_size_grams": i.pack_size_grams,
            "packets_per_carton": i.packets_per_carton,
            "hsn_code": i.hsn_code,
            "gst_rate_pct": float(i.gst_rate_pct),
            "selling_price_rupees": from_paise_float(i.selling_price_paise),
            "standard_rate_rupees": from_paise_float(i.standard_rate_paise),
            "current_stock": float(get_item_balance(db, i.id)),
            "wac_rupees": from_paise_float(get_weighted_avg_cost_paise(db, i.id)),
            "reorder_level": float(i.reorder_level)
        } for i in items],
        "customers": [{
            "id": c.id,
            "code": c.code,
            "name": c.name,
            "customer_type": c.customer_type,
            "gstin": c.gstin,
            "state_code": c.state_code,
            "state_name": c.state_name,
            "address": c.address
        } for c in customers],
        "boms": [{
            "id": b.id,
            "finished_item_id": b.finished_item_id,
            "finished_item_name": b.finished_item.name,
            "expected_yield_packets": float(b.expected_yield_packets),
            "tolerance_pct": float(b.tolerance_pct),
            "lines": [{
                "component_item_id": l.component_item_id,
                "component_name": l.component_item.name,
                "qty_per_batch": float(l.qty_per_batch),
                "unit": l.unit
            } for l in b.lines]
        } for b in boms]
    }

# --- PURCHASES ---
@app.post("/api/purchases")
def create_purchase_api(
    req: PurchaseReq,
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.PRODUCTION, UserRole.OWNER)),
    db: Session = Depends(get_db)
):
    items_payload = [{
        "item_id": l.item_id,
        "qty": l.qty,
        "rate_paise": to_paise(l.rate_rupees),
        "batch_no": l.batch_no,
        "expiry_date": l.expiry_date
    } for l in req.items]
    p = record_purchase(db, user, req.supplier_name, req.invoice_ref, req.purchase_date or date.today(), items_payload)
    return {"id": p.id, "purchase_number": p.purchase_number}

# --- PRODUCTION ---
@app.post("/api/production/runs")
def create_production_run_api(
    req: ProductionRunReq,
    user: User = Depends(require_roles(UserRole.PRODUCTION, UserRole.ADMIN, UserRole.OWNER)),
    db: Session = Depends(get_db)
):
    try:
        run = record_production_run(
            db, user, req.finished_item_id,
            Decimal(str(req.batch_multiplier)),
            Decimal(str(req.actual_output_packets)),
            [c.model_dump() for c in req.consumptions],
            to_paise(req.labour_cost_rupees),
            to_paise(req.overhead_cost_rupees),
            req.run_date
        )
        return {
            "id": run.id,
            "run_number": run.run_number,
            "yield_variance_pct": float(run.yield_variance_pct),
            "yield_flagged": run.yield_flagged,
            "cost_per_packet_rupees": from_paise_float(run.cost_per_packet_paise)
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.patch("/api/production/runs/{run_id}/overheads")
def patch_run_overheads_api(
    run_id: int,
    req: OverheadUpdateReq,
    user: User = Depends(require_roles(UserRole.PRODUCTION, UserRole.ADMIN, UserRole.OWNER)),
    db: Session = Depends(get_db)
):
    run = update_run_overheads(db, user, run_id, to_paise(req.labour_cost_rupees), to_paise(req.overhead_cost_rupees))
    return {
        "id": run.id,
        "run_number": run.run_number,
        "total_cost_rupees": from_paise_float(run.total_cost_paise),
        "cost_per_packet_rupees": from_paise_float(run.cost_per_packet_paise)
    }

@app.get("/api/production/planning")
def production_planning_hint(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Stretch goal: Production planning from pending orders."""
    pending = db.query(SalesOrder).filter(SalesOrder.status == "submitted").all()
    demand = {}
    for o in pending:
        for ln in o.lines:
            demand[ln.item_id] = demand.get(ln.item_id, Decimal("0")) + Decimal(str(ln.qty_packets))
    suggestions = []
    for item_id, req_qty in demand.items():
        item = db.query(Item).filter(Item.id == item_id).first()
        bom = db.query(BOMHeader).filter(BOMHeader.finished_item_id == item_id).first()
        avail = get_item_balance(db, item_id)
        shortfall = max(Decimal("0"), req_qty - avail)
        batches = float((shortfall / Decimal(str(bom.expected_yield_packets))).quantize(Decimal("0.01"))) if (bom and shortfall > 0) else 0
        suggestions.append({
            "product": item.name,
            "pending_order_qty": float(req_qty),
            "available_stock": float(avail),
            "shortfall": float(shortfall),
            "recommended_batches": batches
        })
    return {"suggestions": suggestions}

# --- SALES ORDERS, APPROVAL, INVOICES & PAYMENTS ---
@app.post("/api/orders")
def submit_order_api(
    req: OrderReq,
    user: User = Depends(require_roles(UserRole.SALESMAN, UserRole.ADMIN, UserRole.OWNER)),
    db: Session = Depends(get_db)
):
    lines_in = [{
        "item_id": l.item_id,
        "qty_packets": l.qty_packets,
        "unit_price_paise": to_paise(l.unit_price_rupees) if l.unit_price_rupees is not None else None
    } for l in req.lines]
    order = create_sales_order(db, user, req.customer_id, lines_in, req.notes, req.client_offline_uuid, req.gps_lat, req.gps_lng)
    return {"id": order.id, "order_number": order.order_number, "status": order.status.value}

@app.get("/api/orders")
def list_orders_api(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(SalesOrder).order_by(SalesOrder.id.desc())
    if user.role == UserRole.SALESMAN:
        q = q.filter(SalesOrder.salesman_id == user.id)
    orders = q.all()
    out = []
    for o in orders:
        stock_chk = check_order_stock(db, o)
        out.append({
            "id": o.id,
            "order_number": o.order_number,
            "order_date": str(o.order_date),
            "customer_id": o.customer_id,
            "customer_name": o.customer.name,
            "customer_state": o.customer.state_name,
            "salesman_name": o.salesman.full_name,
            "status": o.status.value,
            "notes": o.notes,
            "stock_check": stock_chk,
            "lines": [{
                "item_id": l.item_id,
                "item_name": l.item.name,
                "qty_packets": float(l.qty_packets),
                "unit_price_rupees": from_paise_float(l.unit_price_paise),
                "line_total_rupees": from_paise_float(int(Decimal(str(l.qty_packets)) * Decimal(l.unit_price_paise)))
            } for l in o.lines]
        })
    return {"orders": out}

@app.post("/api/orders/{order_id}/approve-invoice")
def approve_order_api(
    order_id: int,
    req: ApproveOrderReq,
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: Session = Depends(get_db)
):
    edited = None
    if req.edited_lines:
        edited = [{
            "item_id": l.item_id,
            "qty_packets": l.qty_packets,
            "unit_price_paise": to_paise(l.unit_price_rupees)
        } for l in req.edited_lines]
    try:
        inv = approve_and_invoice_order(db, user, order_id, edited, req.allow_backorder_override)
        return {
            "invoice_id": inv.id,
            "invoice_number": inv.invoice_number,
            "taxable_rupees": from_paise_float(inv.taxable_paise),
            "cgst_rupees": from_paise_float(inv.cgst_paise),
            "sgst_rupees": from_paise_float(inv.sgst_paise),
            "igst_rupees": from_paise_float(inv.igst_paise),
            "grand_total_rupees": from_paise_float(inv.grand_total_paise)
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/invoices")
def list_invoices_api(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    invs = db.query(Invoice).order_by(Invoice.id.desc()).all()
    return {
        "invoices": [{
            "id": i.id,
            "invoice_number": i.invoice_number,
            "invoice_date": str(i.invoice_date),
            "order_number": i.order.order_number,
            "customer_name": i.customer.name,
            "customer_phone": i.customer.phone or "",
            "place_of_supply": f"{i.place_of_supply_name} ({i.place_of_supply_code})",
            "is_interstate": i.is_interstate,
            "taxable_rupees": from_paise_float(i.taxable_paise),
            "cgst_rupees": from_paise_float(i.cgst_paise),
            "sgst_rupees": from_paise_float(i.sgst_paise),
            "igst_rupees": from_paise_float(i.igst_paise),
            "grand_total_rupees": from_paise_float(i.grand_total_paise),
            "paid_rupees": from_paise_float(i.paid_paise),
            "outstanding_rupees": from_paise_float(i.grand_total_paise - i.paid_paise),
            "status": i.status,
            "credit_note_number": i.credit_note_number
        } for i in invs]
    }

@app.post("/api/invoices/{invoice_id}/dispatch")
def dispatch_invoice_api(
    invoice_id: int,
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: Session = Depends(get_db)
):
    try:
        inv = dispatch_invoice(db, user, invoice_id)
        return {"id": inv.id, "invoice_number": inv.invoice_number, "status": inv.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/invoices/{invoice_id}/cancel")
def cancel_invoice_api(
    invoice_id: int,
    req: CancelInvoiceReq,
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: Session = Depends(get_db)
):
    try:
        inv = cancel_invoice_with_credit_note(db, user, invoice_id, req.reason)
        return {"id": inv.id, "invoice_number": inv.invoice_number, "credit_note_number": inv.credit_note_number}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/invoices/{invoice_id}/pdf")
def download_invoice_pdf(invoice_id: int, db: Session = Depends(get_db)):
    pdf_bytes = build_gst_invoice_pdf(db, invoice_id)
    inv = db.query(Invoice).filter(Invoice.id == invoice_id).one()
    fname = inv.invoice_number.replace("/", "_") + ".pdf"
    return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename={fname}"})

@app.post("/api/payments")
def record_payment_api(
    req: PaymentReq,
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.OWNER)),
    db: Session = Depends(get_db)
):
    try:
        pmt = record_payment(db, user, req.invoice_id, to_paise(req.amount_rupees), req.mode, req.reference_no, req.payment_date)
        return {"id": pmt.id, "receipt_number": pmt.receipt_number}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- REPORTS & EXPORTS ---
@app.get("/api/reports/monthly")
def monthly_reports_api(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return get_monthly_audit_reports(db, start_date, end_date)

@app.get("/api/reports/export/excel")
def export_excel_api(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db)
):
    rep = get_monthly_audit_reports(db, start_date, end_date)
    xlsx = export_audit_excel(rep)
    return Response(
        content=xlsx,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=Kaveri_Monthly_Audit_Pack.xlsx"}
    )

@app.get("/api/reports/export/tally-xml")
def export_tally_api(
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    db: Session = Depends(get_db)
):
    rep = get_monthly_audit_reports(db, start_date, end_date)
    xml_str = export_tally_xml(rep)
    return Response(
        content=xml_str,
        media_type="application/xml",
        headers={"Content-Disposition": "attachment; filename=Kaveri_Tally_Vouchers.xml"}
    )

@app.get("/api/audit-logs")
def get_audit_logs_api(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    logs = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(100).all()
    return {
        "logs": [{
            "id": l.id,
            "timestamp": l.timestamp.isoformat(),
            "username": l.username,
            "action": l.action,
            "entity_type": l.entity_type,
            "entity_id": l.entity_id,
            "details": l.details
        } for l in logs]
    }

# Serve Single-Page Web & Mobile PWA Frontend
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend"))
if os.path.exists(FRONTEND_DIR):
    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
