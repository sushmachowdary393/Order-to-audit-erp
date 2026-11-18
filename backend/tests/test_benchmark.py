import os
import sys
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.models import Base, User, Item, Customer, StockLedger
from app.seed import reset_and_seed_benchmark
from app.services import (
    to_paise, from_paise, from_paise_float, get_item_balance, get_weighted_avg_cost_paise,
    convert_unit, record_purchase, record_production_run, update_run_overheads,
    create_sales_order, check_order_stock, approve_and_invoice_order,
    dispatch_invoice, cancel_invoice_with_credit_note, record_payment
)
from app.reports import get_monthly_audit_reports, build_gst_invoice_pdf, export_audit_excel, export_tally_xml

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    reset_and_seed_benchmark(session)
    yield session
    session.close()

def test_unit_conversions():
    assert convert_unit(Decimal("1.5"), "kg", "g") == Decimal("1500.0000")
    assert convert_unit(Decimal("250"), "g", "kg") == Decimal("0.2500")
    assert convert_unit(Decimal("10"), "carton", "packet", packets_per_carton=20) == Decimal("200.0000")
    assert convert_unit(Decimal("180"), "packet", "carton", packets_per_carton=20) == Decimal("9.0000")

def test_section_5_benchmark_end_to_end(db):
    admin = db.query(User).filter_by(username="admin").one()
    prod_user = db.query(User).filter_by(username="production").one()
    salesman_a = db.query(User).filter_by(username="salesman_a").one()
    salesman_b = db.query(User).filter_by(username="salesman_b").one()

    flour = db.query(Item).filter_by(sku="RM-FLOUR").one()
    oil = db.query(Item).filter_by(sku="RM-OIL").one()
    spice = db.query(Item).filter_by(sku="RM-SPICE").one()
    pouch = db.query(Item).filter_by(sku="PK-POUCH200").one()
    carton = db.query(Item).filter_by(sku="PK-CARTON20").one()
    murukku = db.query(Item).filter_by(sku="FG-MUR200").one()

    retailer_a = db.query(Customer).filter_by(code="CUST-001").one()
    distributor_b = db.query(Customer).filter_by(code="CUST-002").one()

    # Step 1: Record a purchase of 60 kg flour at Rs 45/kg
    record_purchase(db, admin, "Cauvery Agro Flour Mills", "INV-CA-101", date.today(), [
        {"item_id": flour.id, "qty": 60, "rate_paise": to_paise(45)}
    ])
    assert get_item_balance(db, flour.id) == Decimal("160.0000")
    # Weighted average rate for flour: (100*42 + 60*45) / 160 = 6900 / 160 = Rs 43.125 -> 4313 paise
    assert get_weighted_avg_cost_paise(db, flour.id) == 4313

    # Step 2 & 3: Start 1 production run of Murukku 200g; issue 40 kg flour, 10.5 L oil, 1.2 kg spice;
    # record actual output 188 good packets, 6 pouches damaged, 9 cartons used
    run = record_production_run(
        db=db,
        user=prod_user,
        finished_item_id=murukku.id,
        batch_multiplier=Decimal("1"),
        actual_output_packets=Decimal("188"),
        consumptions_in=[
            {"item_id": flour.id, "actual_good_qty": 40, "damaged_wastage_qty": 0},
            {"item_id": oil.id, "actual_good_qty": 10.5, "damaged_wastage_qty": 0},
            {"item_id": spice.id, "actual_good_qty": 1.2, "damaged_wastage_qty": 0},
            {"item_id": pouch.id, "actual_good_qty": 188, "damaged_wastage_qty": 6},
            {"item_id": carton.id, "actual_good_qty": 9, "damaged_wastage_qty": 0},
        ]
    )

    # Check closing raw & packaging balances & finished goods after run
    assert get_item_balance(db, flour.id) == Decimal("120.0000")
    assert get_item_balance(db, oil.id) == Decimal("19.5000")
    assert get_item_balance(db, pouch.id) == Decimal("306.0000")
    assert get_item_balance(db, carton.id) == Decimal("21.0000")
    assert get_item_balance(db, murukku.id) == Decimal("238.0000")

    # Check Yield variance (-6.00%, flagged) and Oil consumption variance (+5.00%, flagged)
    assert run.yield_variance_pct == Decimal("-6.00")
    assert run.yield_flagged is True
    oil_cons = [c for c in run.consumptions if c.item_id == oil.id][0]
    assert oil_cons.variance_pct == Decimal("5.00")
    assert oil_cons.variance_flagged is True

    # Step 4: Salesman A places order for Retailer A (Tamil Nadu): 150 packets
    ord_a = create_sales_order(db, salesman_a, retailer_a.id, [{"item_id": murukku.id, "qty_packets": 150}])

    # Step 5: Admin approves, raises GST invoice (CGST + SGST), and records dispatch
    inv_a = approve_and_invoice_order(db, admin, ord_a.id)
    assert inv_a.taxable_paise == 750000     # Rs 7,500.00
    assert inv_a.cgst_paise == 18750         # Rs 187.50
    assert inv_a.sgst_paise == 18750         # Rs 187.50
    assert inv_a.igst_paise == 0
    assert inv_a.grand_total_paise == 787500 # Rs 7,875.00

    dispatch_invoice(db, admin, inv_a.id)
    assert get_item_balance(db, murukku.id) == Decimal("88.0000")

    # Step 6: Salesman B places order for Distributor B (Karnataka): 120 packets -> Insufficient stock flagged (shortage 32)
    ord_b = create_sales_order(db, salesman_b, distributor_b.id, [{"item_id": murukku.id, "qty_packets": 120}])
    chk_b = check_order_stock(db, ord_b)
    assert chk_b["all_sufficient"] is False
    assert chk_b["lines"][0]["shortage_qty"] == 32.0
    assert "IGST" in chk_b["tax_regime"]
    with pytest.raises(ValueError, match="short by 32 packets"):
        approve_and_invoice_order(db, admin, ord_b.id)

    # Step 7: Record payment of Rs 4,000 from Retailer A -> Outstanding Rs 3,875
    record_payment(db, admin, inv_a.id, to_paise(4000), "NEFT", "UTR2026111701")
    db.refresh(inv_a)
    assert (inv_a.grand_total_paise - inv_a.paid_paise) == 387500  # Rs 3,875.00

    # Step 8: Add labour Rs 1,200 and gas/power Rs 600 for the run -> Cost per packet
    run = update_run_overheads(db, prod_user, run.id, to_paise(1200), to_paise(600))
    # Material cost:
    # Flour: 40 * 43.13 = 1725.20
    # Oil: 10.5 * 140.00 = 1470.00
    # Spice: 1.2 * 200.00 = 240.00
    # Pouches: 194 * 2.50 = 485.00
    # Cartons: 9 * 15.00 = 135.00
    # Total Material = 4055.20 + Labour 1200 + Overhead 600 = 5855.20 / 188 = Rs 31.14 / packet
    assert from_paise(run.material_cost_paise) == "4055.20"
    assert from_paise(run.total_cost_paise) == "5855.20"
    assert from_paise(run.cost_per_packet_paise) == "31.14"

    # Step 9: Monthly reports, PDF invoice, Excel workbook, Tally XML
    rep = get_monthly_audit_reports(db)
    assert len(rep["sales_register"]) == 1
    assert rep["receivables_ageing"][0]["outstanding"] == 3875.0
    pdf_bytes = build_gst_invoice_pdf(db, inv_a.id)
    assert pdf_bytes[:4] == b"%PDF"
    xlsx_bytes = export_audit_excel(rep)
    assert len(xlsx_bytes) > 1000
    xml_out = export_tally_xml(rep)
    assert "FY26-27/INV/0001" in xml_out
