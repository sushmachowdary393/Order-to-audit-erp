from datetime import date, timedelta
from decimal import Decimal
import hashlib
from sqlalchemy.orm import Session
from .models import (
    User, UserRole, Customer, Supplier, Item, ItemType, BOMHeader, BOMLine,
    StockLedger, StockMovementType, AuditLog
)
from .services import to_paise, dec

def hash_pw(pw: str) -> str:
    return hashlib.sha256(f"kaveri_salt_{pw}".encode()).hexdigest()

def reset_and_seed_benchmark(db: Session):
    from .models import (
        Payment, InvoiceLine, Invoice, SalesOrderLine, SalesOrder,
        ProductionConsumption, ProductionRun, PurchaseLine, Purchase,
        BOMLine, BOMHeader, StockLedger, AuditLog, Item, Customer, Supplier, User
    )
    for model in [
        Payment, InvoiceLine, Invoice, SalesOrderLine, SalesOrder,
        ProductionConsumption, ProductionRun, PurchaseLine, Purchase,
        BOMLine, BOMHeader, StockLedger, AuditLog, Item, Customer, Supplier, User
    ]:
        db.query(model).delete()
    db.commit()

    # Users (5 roles: Salesman A, Salesman B, Factory Admin, Production Supervisor, Auditor, Owner)
    users = [
        User(username="salesman_a", full_name="Karthik (Salesman A)", password_hash=hash_pw("pass123"), role=UserRole.SALESMAN),
        User(username="salesman_b", full_name="Suresh (Salesman B)", password_hash=hash_pw("pass123"), role=UserRole.SALESMAN),
        User(username="admin", full_name="Meenakshi (Factory Admin)", password_hash=hash_pw("pass123"), role=UserRole.ADMIN),
        User(username="production", full_name="Murugan (Production Supervisor)", password_hash=hash_pw("pass123"), role=UserRole.PRODUCTION),
        User(username="auditor", full_name="CA Raghavan (Auditor)", password_hash=hash_pw("pass123"), role=UserRole.AUDITOR),
        User(username="owner", full_name="Anand (Factory Owner)", password_hash=hash_pw("pass123"), role=UserRole.OWNER),
    ]
    db.add_all(users)
    db.flush()
    u_map = {u.username: u for u in users}

    # Customers (Retailers & Distributors across Tamil Nadu, Karnataka, Andhra Pradesh & Kerala)
    custs = [
        Customer(
            code="CUST-001", name="Retailer A (Sri Balaji Stores)", customer_type="Retailer",
            gstin="33AABCS9102K1Z1", state_code="33", state_name="Tamil Nadu",
            address="14 NSB Road, Tiruchirappalli, TN 620002", phone="9842411001",
            assigned_salesman_id=u_map["salesman_a"].id
        ),
        Customer(
            code="CUST-002", name="Distributor B (Nandi Wholesale)", customer_type="Distributor",
            gstin="29AABCN4810M1Z8", state_code="29", state_name="Karnataka",
            address="88 APMC Yard, Yeshwanthpur, Bengaluru, KA 560022", phone="9845022002",
            assigned_salesman_id=u_map["salesman_b"].id
        ),
        Customer(
            code="CUST-003", name="Madurai Meenakshi Supermart", customer_type="Retailer",
            gstin="33AABCM7721P1Z4", state_code="33", state_name="Tamil Nadu",
            address="42 Anna Nagar East, Madurai, TN 625020", phone="9843033003",
            assigned_salesman_id=u_map["salesman_a"].id
        ),
        Customer(
            code="CUST-004", name="Thanjavur Cauvery Departmental Store", customer_type="Retailer",
            gstin="33AABCT6129R1Z2", state_code="33", state_name="Tamil Nadu",
            address="19 Gandhiji Road, Thanjavur, TN 613001", phone="9842644004",
            assigned_salesman_id=u_map["salesman_a"].id
        ),
        Customer(
            code="CUST-005", name="Coimbatore Kovai Pazhamudir Nilayam", customer_type="Retailer",
            gstin="33AABCK8834L1Z9", state_code="33", state_name="Tamil Nadu",
            address="105 Cross Cut Road, Gandhipuram, Coimbatore, TN 641012", phone="9842255005",
            assigned_salesman_id=u_map["salesman_a"].id
        ),
        Customer(
            code="CUST-006", name="Salem Saravana Provisions & Snacks", customer_type="Retailer",
            gstin="33AABCS3910D1Z6", state_code="33", state_name="Tamil Nadu",
            address="7 Omalur Main Road, Salem, TN 636004", phone="9842766006",
            assigned_salesman_id=u_map["salesman_a"].id
        ),
        Customer(
            code="CUST-007", name="Chennai T.Nagar Annapoorna Grocers", customer_type="Retailer",
            gstin="33AABCA5018H1Z3", state_code="33", state_name="Tamil Nadu",
            address="63 Usman Road, T. Nagar, Chennai, TN 600017", phone="9840177007",
            assigned_salesman_id=u_map["salesman_a"].id
        ),
        Customer(
            code="CUST-008", name="Mysuru Chamundi Traders", customer_type="Retailer",
            gstin="29AABCC2194F1Z5", state_code="29", state_name="Karnataka",
            address="24 Sayyaji Rao Road, Mysuru, KA 570001", phone="9845188008",
            assigned_salesman_id=u_map["salesman_b"].id
        ),
        Customer(
            code="CUST-009", name="Tirupati Balaji Wholesale Agencies", customer_type="Distributor",
            gstin="37AABCT9045G1Z1", state_code="37", state_name="Andhra Pradesh",
            address="12 Renigunta Road, Tirupati, AP 517501", phone="9849099009",
            assigned_salesman_id=u_map["salesman_b"].id
        ),
        Customer(
            code="CUST-010", name="Kochi Malabar Retail Hub", customer_type="Retailer",
            gstin="32AABCM6612N1Z7", state_code="32", state_name="Kerala",
            address="51 MG Road, Ernakulam, Kochi, KL 682016", phone="9847010010",
            assigned_salesman_id=u_map["salesman_b"].id
        ),
    ]
    db.add_all(custs)

    # Suppliers
    suppliers = [
        Supplier(
            name="Cauvery Agro Flour Mills", gstin="33AABCC5512D1Z9",
            state_code="33", state_name="Tamil Nadu", phone="9443155001"
        ),
        Supplier(
            name="Pollachi Cold-Pressed Oils Pvt Ltd", gstin="33AABCP8123K1Z2",
            state_code="33", state_name="Tamil Nadu", phone="9443266002"
        ),
        Supplier(
            name="Erode Spice & Masala Traders", gstin="33AABCE4419M1Z8",
            state_code="33", state_name="Tamil Nadu", phone="9443377003"
        ),
        Supplier(
            name="Sivakasi FlexiPack & Cartons", gstin="33AABCS7720P1Z4",
            state_code="33", state_name="Tamil Nadu", phone="9443488004"
        ),
    ]
    db.add_all(suppliers)
    db.flush()

    # Master Items: Raw Materials & Packaging
    flour = Item(
        sku="RM-FLOUR", name="Rice & Urad Flour Mix", item_type=ItemType.RAW_MATERIAL,
        base_unit="kg", hsn_code="11029090", gst_rate_pct=Decimal("5.00"),
        standard_rate_paise=to_paise(42), reorder_level=Decimal("50")
    )
    oil = Item(
        sku="RM-OIL", name="Cooking Oil (Refined Groundnut)", item_type=ItemType.RAW_MATERIAL,
        base_unit="L", hsn_code="15089091", gst_rate_pct=Decimal("5.00"),
        standard_rate_paise=to_paise(140), reorder_level=Decimal("20")
    )
    spice = Item(
        sku="RM-SPICE", name="Salt and Spice Mix", item_type=ItemType.RAW_MATERIAL,
        base_unit="kg", hsn_code="09109100", gst_rate_pct=Decimal("5.00"),
        standard_rate_paise=to_paise(200), reorder_level=Decimal("3")
    )
    pouch = Item(
        sku="PK-POUCH200", name="200 g Printed Pouch", item_type=ItemType.PACKAGING,
        base_unit="piece", hsn_code="39232100", gst_rate_pct=Decimal("18.00"),
        standard_rate_paise=to_paise("2.50"), reorder_level=Decimal("200")
    )
    carton = Item(
        sku="PK-CARTON20", name="Carton Box (20-packet)", item_type=ItemType.PACKAGING,
        base_unit="piece", hsn_code="48191010", gst_rate_pct=Decimal("18.00"),
        standard_rate_paise=to_paise(15), reorder_level=Decimal("15")
    )
    besan = Item(
        sku="RM-BESAN", name="Bengal Gram Flour (Besan)", item_type=ItemType.RAW_MATERIAL,
        base_unit="kg", hsn_code="11061000", gst_rate_pct=Decimal("5.00"),
        standard_rate_paise=to_paise(78), reorder_level=Decimal("40")
    )
    nendran = Item(
        sku="RM-BANANA", name="Raw Nendran Banana & Tapioca Slices", item_type=ItemType.RAW_MATERIAL,
        base_unit="kg", hsn_code="08039010", gst_rate_pct=Decimal("5.00"),
        standard_rate_paise=to_paise(48), reorder_level=Decimal("50")
    )
    jaggery = Item(
        sku="RM-JAGGERY", name="Organic Vellam (Jaggery) & Pure Ghee Mix", item_type=ItemType.RAW_MATERIAL,
        base_unit="kg", hsn_code="17011310", gst_rate_pct=Decimal("5.00"),
        standard_rate_paise=to_paise(95), reorder_level=Decimal("25")
    )
    cashew_nuts = Item(
        sku="RM-CASHEW", name="Roasted Cashew, Peanuts & Curry Leaves", item_type=ItemType.RAW_MATERIAL,
        base_unit="kg", hsn_code="08013220", gst_rate_pct=Decimal("5.00"),
        standard_rate_paise=to_paise(420), reorder_level=Decimal("10")
    )
    pouch_500 = Item(
        sku="PK-POUCH500", name="500 g Family Stand-Up Pouch", item_type=ItemType.PACKAGING,
        base_unit="piece", hsn_code="39232100", gst_rate_pct=Decimal("18.00"),
        standard_rate_paise=to_paise("4.20"), reorder_level=Decimal("150")
    )
    sweet_box = Item(
        sku="PK-SWTBOX250", name="250 g Food-Grade Sweet Box", item_type=ItemType.PACKAGING,
        base_unit="piece", hsn_code="48192090", gst_rate_pct=Decimal("18.00"),
        standard_rate_paise=to_paise("5.50"), reorder_level=Decimal("120")
    )

    # Finished Goods across all 4 core South Indian snack categories:
    # Category 1: Murukku
    murukku_200 = Item(
        sku="FG-MUR200", name="Murukku 200 g", item_type=ItemType.FINISHED_GOOD,
        base_unit="packet", pack_size_grams=200, packets_per_carton=20,
        hsn_code="21069099", gst_rate_pct=Decimal("5.00"),
        selling_price_paise=to_paise(50), standard_rate_paise=to_paise("27.00"),
        reorder_level=Decimal("100")
    )
    butter_murukku_200 = Item(
        sku="FG-BMUR200", name="Butter Murukku 200 g", item_type=ItemType.FINISHED_GOOD,
        base_unit="packet", pack_size_grams=200, packets_per_carton=20,
        hsn_code="21069099", gst_rate_pct=Decimal("5.00"),
        selling_price_paise=to_paise(55), standard_rate_paise=to_paise("30.00"),
        reorder_level=Decimal("80")
    )
    murukku_500 = Item(
        sku="FG-MUR500", name="Kai Murukku Family Pack 500 g", item_type=ItemType.FINISHED_GOOD,
        base_unit="packet", pack_size_grams=500, packets_per_carton=20,
        hsn_code="21069099", gst_rate_pct=Decimal("5.00"),
        selling_price_paise=to_paise(115), standard_rate_paise=to_paise("64.00"),
        reorder_level=Decimal("60")
    )

    # Category 2: Mixture
    madras_mix_200 = Item(
        sku="FG-MIX200", name="Madras Spicy Mixture 200 g", item_type=ItemType.FINISHED_GOOD,
        base_unit="packet", pack_size_grams=200, packets_per_carton=20,
        hsn_code="21069099", gst_rate_pct=Decimal("5.00"),
        selling_price_paise=to_paise(55), standard_rate_paise=to_paise("31.00"),
        reorder_level=Decimal("80")
    )
    cornflakes_mix_200 = Item(
        sku="FG-CMIX200", name="Special Cashew Cornflakes Mixture 200 g", item_type=ItemType.FINISHED_GOOD,
        base_unit="packet", pack_size_grams=200, packets_per_carton=20,
        hsn_code="21069099", gst_rate_pct=Decimal("5.00"),
        selling_price_paise=to_paise(65), standard_rate_paise=to_paise("37.00"),
        reorder_level=Decimal("70")
    )

    # Category 3: Chips
    banana_chips_200 = Item(
        sku="FG-CHP200", name="Nendran Banana Chips 200 g", item_type=ItemType.FINISHED_GOOD,
        base_unit="packet", pack_size_grams=200, packets_per_carton=20,
        hsn_code="21069099", gst_rate_pct=Decimal("12.00"),
        selling_price_paise=to_paise(65), standard_rate_paise=to_paise("36.00"),
        reorder_level=Decimal("80")
    )
    tapioca_chips_200 = Item(
        sku="FG-TCHP200", name="Spicy Tapioca (Maravalli) Chips 200 g", item_type=ItemType.FINISHED_GOOD,
        base_unit="packet", pack_size_grams=200, packets_per_carton=20,
        hsn_code="21069099", gst_rate_pct=Decimal("12.00"),
        selling_price_paise=to_paise(50), standard_rate_paise=to_paise("28.00"),
        reorder_level=Decimal("80")
    )

    # Category 4: Sweets
    mysore_pak_250 = Item(
        sku="FG-MYS250", name="Ghee Mysore Pak Sweet Box 250 g", item_type=ItemType.FINISHED_GOOD,
        base_unit="packet", pack_size_grams=250, packets_per_carton=20,
        hsn_code="21069099", gst_rate_pct=Decimal("5.00"),
        selling_price_paise=to_paise(140), standard_rate_paise=to_paise("82.00"),
        reorder_level=Decimal("50")
    )
    boondi_laddu_250 = Item(
        sku="FG-LAD250", name="Tirunelveli Motichoor Laddu Sweet Box 250 g", item_type=ItemType.FINISHED_GOOD,
        base_unit="packet", pack_size_grams=250, packets_per_carton=20,
        hsn_code="21069099", gst_rate_pct=Decimal("5.00"),
        selling_price_paise=to_paise(130), standard_rate_paise=to_paise("76.00"),
        reorder_level=Decimal("50")
    )
    jangiri_250 = Item(
        sku="FG-JNG250", name="Saffron Ghee Jangiri Sweet Box 250 g", item_type=ItemType.FINISHED_GOOD,
        base_unit="packet", pack_size_grams=250, packets_per_carton=20,
        hsn_code="21069099", gst_rate_pct=Decimal("5.00"),
        selling_price_paise=to_paise(125), standard_rate_paise=to_paise("72.00"),
        reorder_level=Decimal("50")
    )

    db.add_all([
        flour, oil, spice, pouch, carton,
        besan, nendran, jaggery, cashew_nuts, pouch_500, sweet_box,
        murukku_200, butter_murukku_200, murukku_500,
        madras_mix_200, cornflakes_mix_200,
        banana_chips_200, tapioca_chips_200,
        mysore_pak_250, boondi_laddu_250, jangiri_250
    ])
    db.flush()

    def add_bom(fg_item, yield_pkts, note_txt, lines):
        bh = BOMHeader(
            finished_item_id=fg_item.id,
            expected_yield_packets=Decimal(str(yield_pkts)),
            tolerance_pct=Decimal("3.00"),
            notes=note_txt
        )
        db.add(bh)
        db.flush()
        db.add_all([
            BOMLine(bom_id=bh.id, component_item_id=comp.id, qty_per_batch=Decimal(str(qty)), unit=unit)
            for comp, qty, unit in lines
        ])

    # 1. Benchmark BOM: Murukku 200 g
    add_bom(murukku_200, 200, "Standard recipe for 1 batch = 200 packets of 200g Murukku", [
        (flour, 40, "kg"), (oil, 10, "L"), (spice, 1.2, "kg"), (pouch, 200, "piece"), (carton, 10, "piece")
    ])
    # 2. Butter Murukku 200 g
    add_bom(butter_murukku_200, 200, "Butter Murukku recipe: 1 batch = 200 packets", [
        (flour, 36, "kg"), (besan, 4, "kg"), (oil, 10.5, "L"), (spice, 1.0, "kg"), (pouch, 200, "piece"), (carton, 10, "piece")
    ])
    # 3. Kai Murukku Family Pack 500 g
    add_bom(murukku_500, 80, "Family 500g pack recipe: 1 batch = 80 packets", [
        (flour, 40, "kg"), (oil, 10, "L"), (spice, 1.2, "kg"), (pouch_500, 80, "piece"), (carton, 4, "piece")
    ])
    # 4. Madras Spicy Mixture 200 g
    add_bom(madras_mix_200, 200, "Madras Mixture recipe: 1 batch = 200 packets", [
        (besan, 32, "kg"), (cashew_nuts, 5, "kg"), (oil, 11, "L"), (spice, 1.5, "kg"), (pouch, 200, "piece"), (carton, 10, "piece")
    ])
    # 5. Special Cashew Cornflakes Mixture 200 g
    add_bom(cornflakes_mix_200, 200, "Cashew Mixture recipe: 1 batch = 200 packets", [
        (besan, 28, "kg"), (cashew_nuts, 8, "kg"), (oil, 10, "L"), (spice, 1.4, "kg"), (pouch, 200, "piece"), (carton, 10, "piece")
    ])
    # 6. Nendran Banana Chips 200 g
    add_bom(banana_chips_200, 150, "Nendran Banana Chips recipe: 1 batch = 150 packets", [
        (nendran, 55, "kg"), (oil, 12, "L"), (spice, 0.8, "kg"), (pouch, 150, "piece"), (carton, 8, "piece")
    ])
    # 7. Spicy Tapioca Chips 200 g
    add_bom(tapioca_chips_200, 160, "Tapioca Chips recipe: 1 batch = 160 packets", [
        (nendran, 52, "kg"), (oil, 11.5, "L"), (spice, 1.2, "kg"), (pouch, 160, "piece"), (carton, 8, "piece")
    ])
    # 8. Ghee Mysore Pak Sweet Box 250 g
    add_bom(mysore_pak_250, 120, "Traditional Ghee Mysore Pak recipe: 1 batch = 120 boxes", [
        (besan, 12, "kg"), (jaggery, 22, "kg"), (sweet_box, 120, "piece"), (carton, 6, "piece")
    ])
    # 9. Tirunelveli Motichoor Laddu Sweet Box 250 g
    add_bom(boondi_laddu_250, 120, "Boondi Laddu Sweet recipe: 1 batch = 120 boxes", [
        (besan, 14, "kg"), (jaggery, 20, "kg"), (cashew_nuts, 2, "kg"), (sweet_box, 120, "piece"), (carton, 6, "piece")
    ])
    # 10. Saffron Ghee Jangiri Sweet Box 250 g
    add_bom(jangiri_250, 120, "Saffron Jangiri Sweet recipe: 1 batch = 120 boxes", [
        (flour, 13, "kg"), (jaggery, 21, "kg"), (oil, 6, "L"), (sweet_box, 120, "piece"), (carton, 6, "piece")
    ])

    # Opening Stock Ledger Entries (Exact Section 5 Benchmark values + opening stock for all items)
    opening_date = date.today().replace(day=1)
    openings = [
        # Benchmark exact opening stock
        (flour, Decimal("100"), to_paise(42), "OPEN-FLOUR-01", date.today() + timedelta(days=120)),
        (oil, Decimal("30"), to_paise(140), "OPEN-OIL-01", date.today() + timedelta(days=180)),
        (spice, Decimal("5"), to_paise(200), "OPEN-SPICE-01", date.today() + timedelta(days=150)),
        (pouch, Decimal("500"), to_paise("2.50"), "OPEN-POUCH-01", None),
        (carton, Decimal("30"), to_paise(15), "OPEN-CARTON-01", None),
        (murukku_200, Decimal("50"), to_paise("27.00"), "OPEN-FG-01", date.today() + timedelta(days=75)),
        # Additional raw materials & packaging
        (besan, Decimal("90"), to_paise(78), "OPEN-BESAN-01", date.today() + timedelta(days=120)),
        (nendran, Decimal("140"), to_paise(48), "OPEN-BANANA-01", date.today() + timedelta(days=15)),
        (jaggery, Decimal("80"), to_paise(95), "OPEN-JAG-01", date.today() + timedelta(days=180)),
        (cashew_nuts, Decimal("35"), to_paise(420), "OPEN-CSH-01", date.today() + timedelta(days=150)),
        (pouch_500, Decimal("250"), to_paise("4.20"), "OPEN-P500-01", None),
        (sweet_box, Decimal("360"), to_paise("5.50"), "OPEN-SBOX-01", None),
        # Finished products across Murukku, Mixture, Chips & Sweets
        (butter_murukku_200, Decimal("80"), to_paise("30.00"), "OPEN-BMUR200-01", date.today() + timedelta(days=75)),
        (murukku_500, Decimal("60"), to_paise("64.00"), "OPEN-MUR500-01", date.today() + timedelta(days=75)),
        (madras_mix_200, Decimal("120"), to_paise("31.00"), "OPEN-MIX200-01", date.today() + timedelta(days=75)),
        (cornflakes_mix_200, Decimal("95"), to_paise("37.00"), "OPEN-CMIX200-01", date.today() + timedelta(days=75)),
        (banana_chips_200, Decimal("90"), to_paise("36.00"), "OPEN-CHP200-01", date.today() + timedelta(days=60)),
        (tapioca_chips_200, Decimal("110"), to_paise("28.00"), "OPEN-TCHP200-01", date.today() + timedelta(days=60)),
        (mysore_pak_250, Decimal("50"), to_paise("82.00"), "OPEN-MYS250-01", date.today() + timedelta(days=45)),
        (boondi_laddu_250, Decimal("55"), to_paise("76.00"), "OPEN-LAD250-01", date.today() + timedelta(days=45)),
        (jangiri_250, Decimal("45"), to_paise("72.00"), "OPEN-JNG250-01", date.today() + timedelta(days=30)),
    ]
    for item, qty, cost_p, batch, exp in openings:
        db.add(StockLedger(
            txn_date=opening_date,
            item_id=item.id,
            movement_type=StockMovementType.OPENING,
            qty_delta=qty,
            unit_cost_paise=cost_p,
            source_type="OPENING",
            source_id=0,
            source_ref="OPENING-BAL",
            batch_no=batch,
            expiry_date=exp,
            notes="Opening stock balance",
            created_by_id=u_map["admin"].id
        ))

    db.add(AuditLog(
        user_id=u_map["admin"].id,
        username="admin",
        action="SYSTEM_SEED",
        entity_type="System",
        entity_id="BENCHMARK_2026_FULL_CATALOG",
        details="Loaded Benchmark + South Indian Snacks (Murukku, Mixture, Chips, Sweets) & Retailers"
    ))
    db.commit()
