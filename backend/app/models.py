from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum as PyEnum
from sqlalchemy import (
    Column, Integer, String, Numeric, DateTime, Date, Boolean,
    ForeignKey, Text, Enum, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class UserRole(str, PyEnum):
    SALESMAN = "salesman"
    ADMIN = "admin"
    PRODUCTION = "production"
    AUDITOR = "auditor"
    OWNER = "owner"

class ItemType(str, PyEnum):
    RAW_MATERIAL = "raw_material"
    PACKAGING = "packaging"
    FINISHED_GOOD = "finished_good"

class OrderStatus(str, PyEnum):
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    INVOICED = "invoiced"
    DISPATCHED = "dispatched"

class StockMovementType(str, PyEnum):
    OPENING = "opening"
    PURCHASE = "purchase"
    PRODUCTION_ISSUE = "production_issue"
    PRODUCTION_OUTPUT = "production_output"
    PRODUCTION_WASTAGE = "production_wastage"
    SALES_DISPATCH = "sales_dispatch"
    ADJUSTMENT = "adjustment"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    full_name = Column(String(128), nullable=False)
    password_hash = Column(String(256), nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(32), unique=True, nullable=False)
    name = Column(String(128), nullable=False)
    customer_type = Column(String(32), nullable=False)  # Retailer / Distributor
    gstin = Column(String(15), nullable=True)
    state_code = Column(String(2), nullable=False, default="33")  # 33 = Tamil Nadu, 29 = Karnataka
    state_name = Column(String(64), nullable=False, default="Tamil Nadu")
    address = Column(Text, nullable=True)
    phone = Column(String(20), nullable=True)
    assigned_salesman_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Supplier(Base):
    __tablename__ = "suppliers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(128), nullable=False)
    gstin = Column(String(15), nullable=True)
    state_code = Column(String(2), nullable=False, default="33")
    state_name = Column(String(64), nullable=False, default="Tamil Nadu")
    phone = Column(String(20), nullable=True)

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, index=True)
    sku = Column(String(32), unique=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    item_type = Column(Enum(ItemType), nullable=False)
    base_unit = Column(String(16), nullable=False)  # kg, L, piece, packet
    pack_size_grams = Column(Integer, nullable=True)  # e.g. 200 for Murukku 200g
    packets_per_carton = Column(Integer, nullable=True)  # e.g. 20
    hsn_code = Column(String(8), nullable=False, default="21069099")
    gst_rate_pct = Column(Numeric(5, 2), nullable=False, default=Decimal("5.00"))
    selling_price_paise = Column(Integer, nullable=False, default=0)  # Exclusive of GST
    standard_rate_paise = Column(Integer, nullable=False, default=0)
    reorder_level = Column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    is_active = Column(Boolean, default=True)

class UnitConversion(Base):
    __tablename__ = "unit_conversions"
    id = Column(Integer, primary_key=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=True)
    from_unit = Column(String(16), nullable=False)
    to_unit = Column(String(16), nullable=False)
    factor = Column(Numeric(14, 6), nullable=False)  # 1 from_unit = factor * to_unit

class BOMHeader(Base):
    __tablename__ = "bom_headers"
    id = Column(Integer, primary_key=True, index=True)
    finished_item_id = Column(Integer, ForeignKey("items.id"), unique=True, nullable=False)
    expected_yield_packets = Column(Numeric(12, 4), nullable=False)
    tolerance_pct = Column(Numeric(5, 2), nullable=False, default=Decimal("3.00"))
    notes = Column(Text, nullable=True)
    lines = relationship("BOMLine", back_populates="bom", cascade="all, delete-orphan")
    finished_item = relationship("Item")

class BOMLine(Base):
    __tablename__ = "bom_lines"
    id = Column(Integer, primary_key=True)
    bom_id = Column(Integer, ForeignKey("bom_headers.id"), nullable=False)
    component_item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    qty_per_batch = Column(Numeric(12, 4), nullable=False)
    unit = Column(String(16), nullable=False)
    bom = relationship("BOMHeader", back_populates="lines")
    component_item = relationship("Item")

class Purchase(Base):
    __tablename__ = "purchases"
    id = Column(Integer, primary_key=True, index=True)
    purchase_number = Column(String(32), unique=True, nullable=False)
    supplier_id = Column(Integer, ForeignKey("suppliers.id"), nullable=True)
    supplier_name = Column(String(128), nullable=False)
    invoice_ref = Column(String(64), nullable=True)
    purchase_date = Column(Date, nullable=False, default=date.today)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    lines = relationship("PurchaseLine", back_populates="purchase", cascade="all, delete-orphan")

class PurchaseLine(Base):
    __tablename__ = "purchase_lines"
    id = Column(Integer, primary_key=True)
    purchase_id = Column(Integer, ForeignKey("purchases.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    batch_no = Column(String(32), nullable=True)
    expiry_date = Column(Date, nullable=True)
    qty = Column(Numeric(12, 4), nullable=False)
    unit = Column(String(16), nullable=False)
    rate_paise = Column(Integer, nullable=False)
    gst_rate_pct = Column(Numeric(5, 2), nullable=False, default=Decimal("5.00"))
    taxable_paise = Column(Integer, nullable=False)
    gst_paise = Column(Integer, nullable=False)
    total_paise = Column(Integer, nullable=False)
    purchase = relationship("Purchase", back_populates="lines")
    item = relationship("Item")

class ProductionRun(Base):
    __tablename__ = "production_runs"
    id = Column(Integer, primary_key=True, index=True)
    run_number = Column(String(32), unique=True, nullable=False)
    bom_id = Column(Integer, ForeignKey("bom_headers.id"), nullable=False)
    finished_item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    batch_multiplier = Column(Numeric(10, 4), nullable=False, default=Decimal("1.0000"))
    run_date = Column(Date, nullable=False, default=date.today)
    expected_output_packets = Column(Numeric(12, 4), nullable=False)
    actual_output_packets = Column(Numeric(12, 4), nullable=False)
    yield_variance_pct = Column(Numeric(8, 2), nullable=False)
    yield_flagged = Column(Boolean, default=False)
    labour_cost_paise = Column(Integer, nullable=False, default=0)
    overhead_cost_paise = Column(Integer, nullable=False, default=0)  # gas + power + other
    material_cost_paise = Column(Integer, nullable=False, default=0)
    total_cost_paise = Column(Integer, nullable=False, default=0)
    cost_per_packet_paise = Column(Integer, nullable=False, default=0)
    batch_code = Column(String(32), nullable=True)
    expiry_date = Column(Date, nullable=True)
    status = Column(String(24), nullable=False, default="posted")
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    consumptions = relationship("ProductionConsumption", back_populates="run", cascade="all, delete-orphan")
    finished_item = relationship("Item")

class ProductionConsumption(Base):
    __tablename__ = "production_consumptions"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("production_runs.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    planned_qty = Column(Numeric(12, 4), nullable=False)
    actual_good_qty = Column(Numeric(12, 4), nullable=False)
    damaged_wastage_qty = Column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    total_consumed_qty = Column(Numeric(12, 4), nullable=False)
    variance_qty = Column(Numeric(12, 4), nullable=False)
    variance_pct = Column(Numeric(8, 2), nullable=False)
    variance_flagged = Column(Boolean, default=False)
    unit_rate_paise = Column(Integer, nullable=False)
    total_cost_paise = Column(Integer, nullable=False)
    run = relationship("ProductionRun", back_populates="consumptions")
    item = relationship("Item")

class SalesOrder(Base):
    __tablename__ = "sales_orders"
    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(32), unique=True, nullable=False)
    client_offline_uuid = Column(String(64), unique=True, nullable=True)  # Idempotency for offline sync
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    salesman_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    order_date = Column(Date, nullable=False, default=date.today)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.SUBMITTED)
    notes = Column(Text, nullable=True)
    gps_lat = Column(String(32), nullable=True)
    gps_lng = Column(String(32), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    customer = relationship("Customer")
    salesman = relationship("User")
    lines = relationship("SalesOrderLine", back_populates="order", cascade="all, delete-orphan")

class SalesOrderLine(Base):
    __tablename__ = "sales_order_lines"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    qty_packets = Column(Numeric(12, 4), nullable=False)
    unit_price_paise = Column(Integer, nullable=False)
    order = relationship("SalesOrder", back_populates="lines")
    item = relationship("Item")

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    invoice_number = Column(String(32), unique=True, nullable=False)  # FY26-27/INV/0001
    financial_year = Column(String(16), nullable=False, default="2026-27")
    order_id = Column(Integer, ForeignKey("sales_orders.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    invoice_date = Column(Date, nullable=False, default=date.today)
    place_of_supply_code = Column(String(2), nullable=False)
    place_of_supply_name = Column(String(64), nullable=False)
    is_interstate = Column(Boolean, nullable=False, default=False)
    taxable_paise = Column(Integer, nullable=False)
    cgst_paise = Column(Integer, nullable=False, default=0)
    sgst_paise = Column(Integer, nullable=False, default=0)
    igst_paise = Column(Integer, nullable=False, default=0)
    grand_total_paise = Column(Integer, nullable=False)
    paid_paise = Column(Integer, nullable=False, default=0)
    status = Column(String(24), nullable=False, default="invoiced")  # invoiced, dispatched, cancelled_credit_note
    dispatched_at = Column(DateTime, nullable=True)
    credit_note_number = Column(String(32), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    customer = relationship("Customer")
    order = relationship("SalesOrder")
    lines = relationship("InvoiceLine", back_populates="invoice", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="invoice")

class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id = Column(Integer, primary_key=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    hsn_code = Column(String(8), nullable=False)
    qty_packets = Column(Numeric(12, 4), nullable=False)
    unit_price_paise = Column(Integer, nullable=False)
    taxable_paise = Column(Integer, nullable=False)
    gst_rate_pct = Column(Numeric(5, 2), nullable=False)
    cgst_paise = Column(Integer, nullable=False, default=0)
    sgst_paise = Column(Integer, nullable=False, default=0)
    igst_paise = Column(Integer, nullable=False, default=0)
    total_paise = Column(Integer, nullable=False)
    invoice = relationship("Invoice", back_populates="lines")
    item = relationship("Item")

class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True, index=True)
    receipt_number = Column(String(32), unique=True, nullable=False)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    payment_date = Column(Date, nullable=False, default=date.today)
    amount_paise = Column(Integer, nullable=False)
    mode = Column(String(32), nullable=False, default="NEFT/UPI")
    reference_no = Column(String(64), nullable=True)
    recorded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    invoice = relationship("Invoice", back_populates="payments")
    customer = relationship("Customer")

class StockLedger(Base):
    """Immutable append-only stock movement ledger. Current balance = SUM(qty_delta)."""
    __tablename__ = "stock_ledger"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    txn_date = Column(Date, default=date.today, nullable=False, index=True)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False, index=True)
    movement_type = Column(Enum(StockMovementType), nullable=False)
    qty_delta = Column(Numeric(12, 4), nullable=False)  # + for inflow, - for outflow
    unit_cost_paise = Column(Integer, nullable=False, default=0)
    source_type = Column(String(32), nullable=False)  # OPENING, PURCHASE, PRODUCTION_RUN, INVOICE, ADJUSTMENT
    source_id = Column(Integer, nullable=True)
    source_ref = Column(String(64), nullable=False)
    batch_no = Column(String(32), nullable=True)
    expiry_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    item = relationship("Item")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    username = Column(String(64), nullable=False)
    action = Column(String(64), nullable=False)
    entity_type = Column(String(32), nullable=False)
    entity_id = Column(String(32), nullable=False)
    details = Column(Text, nullable=False)
