"""The reference data for the demo business: Kaveri Knit Fabrics, Tirupur.

A mid-sized knitted-fabric manufacturer: buys yarn and dyes, knits greige,
dyes and finishes it, and ships fabric to garment buyers in India, the UK and
the US. Every figure below is plausible for that business — GSM, widths, yarn
counts, consumption per metre and lead times are the real relationships, which
is what makes the coverage and risk arithmetic meaningful.
"""

from __future__ import annotations

from decimal import Decimal

from textileops.core.units import UnitOfMeasure
from textileops.models.enums import Currency, FabricFinish, MaterialCategory, UserRole

USERS = [
    ("owner@kaveriknits.example", "Ramesh Kaveri", UserRole.OWNER),
    ("ops@kaveriknits.example", "Divya Narayanan", UserRole.OPERATIONS),
    ("procurement@kaveriknits.example", "Suresh Kumar", UserRole.PROCUREMENT),
    ("production@kaveriknits.example", "Anitha Raj", UserRole.PRODUCTION),
    ("quality@kaveriknits.example", "Joseph Mathew", UserRole.QUALITY),
    ("viewer@kaveriknits.example", "Priya Menon", UserRole.VIEWER),
]

CUSTOMERS = [
    # code, name, country, contact, email, currency, terms, tier
    ("CUST-001", "Meridian Apparel Ltd", "United Kingdom", "Helen Whitcombe",
     "helen@meridian-apparel.example", Currency.GBP, 45, 1),
    ("CUST-002", "Northwind Retail Group", "United States", "Dale Ferraro",
     "dale.ferraro@northwind-retail.example", Currency.USD, 60, 2),
    ("CUST-003", "Anand Garments", "India", "Anand Pillai",
     "anand@anandgarments.example", Currency.INR, 30, 3),
    ("CUST-004", "Lyra Fashion House", "India", "Shalini Rao",
     "shalini@lyrafashion.example", Currency.INR, 30, 4),
    ("CUST-005", "Basil & Company", "India", "Basil Thomas",
     "basil@basilco.example", Currency.INR, 21, 5),
]

#: On-time rate is deliberately absent: it is a measurement, derived from real
#: receipt dates by ``procurement.recompute_supplier_on_time_rate``. Seeding a
#: number here would make the supplier page assert something it had not
#: observed. Delivery history is seeded instead (see ``SUPPLIER_HISTORY``), so
#: the rates the UI shows are genuinely earned.
SUPPLIERS = [
    # code, name, contact, email, phone, lead_time_days
    ("SUP-001", "Sri Balaji Spinning Mills", "Karthik Balaji",
     "dispatch@sribalajispinning.example", "+91 422 4455 101", 14),
    ("SUP-002", "Coimbatore Cotton Traders", "Meena Sundaram",
     "sales@cbecotton.example", "+91 422 4455 202", 10),
    ("SUP-003", "Vasanth Dyes & Chemicals", "Vasanth Iyer",
     "orders@vasanthdyes.example", "+91 422 4455 303", 7),
    ("SUP-004", "Precision Knits (Greige)", "Ganesh Murthy",
     "ganesh@precisionknits.example", "+91 421 2233 404", 12),
    ("SUP-005", "PackRight Industries", "Fatima Sheikh",
     "hello@packright.example", "+91 422 4455 505", 5),
]

#: Completed purchase orders from the past few months, so supplier reliability
#: is observed rather than asserted. Sri Balaji has a real history of slipping;
#: that is why the delay in scenario A is not a surprise.
#: (supplier, material, quantity, unit, ordered_days_ago, promised_in_days,
#:  actual_receipt_days_ago)
SUPPLIER_HISTORY = [
    ("SUP-001", "MAT-YRN-40S", Decimal("2400"), UnitOfMeasure.KG, 120, -106, 104),
    ("SUP-001", "MAT-YRN-30S", Decimal("1800"), UnitOfMeasure.KG, 104, -90, 84),
    ("SUP-001", "MAT-YRN-40S", Decimal("3000"), UnitOfMeasure.KG, 88, -74, 74),
    ("SUP-001", "MAT-YRN-30S", Decimal("2200"), UnitOfMeasure.KG, 72, -58, 51),
    ("SUP-001", "MAT-YRN-40S", Decimal("2800"), UnitOfMeasure.KG, 56, -42, 42),
    ("SUP-001", "MAT-YRN-40S", Decimal("2000"), UnitOfMeasure.KG, 40, -26, 20),
    ("SUP-002", "MAT-YRN-PC20", Decimal("4000"), UnitOfMeasure.KG, 96, -86, 86),
    ("SUP-002", "MAT-YRN-PC20", Decimal("3500"), UnitOfMeasure.KG, 64, -54, 55),
    ("SUP-005", "MAT-PKG-POLY", Decimal("20000"), UnitOfMeasure.PIECE, 80, -75, 75),
    ("SUP-005", "MAT-PKG-CTN", Decimal("1200"), UnitOfMeasure.PIECE, 50, -45, 45),
]

MATERIALS = [
    # code, name, category, unit, composition, yarn_count, colour, shade, cost, reorder
    ("MAT-YRN-40S", "40s Combed Cotton Yarn", MaterialCategory.YARN, UnitOfMeasure.KG,
     "100% Cotton", "40s", None, None, Decimal("285.00"), Decimal("1500")),
    ("MAT-YRN-30S", "30s Carded Cotton Yarn", MaterialCategory.YARN, UnitOfMeasure.KG,
     "100% Cotton", "30s", None, None, Decimal("242.00"), Decimal("2000")),
    ("MAT-YRN-PC20", "20s Poly-Cotton Yarn 65/35", MaterialCategory.YARN, UnitOfMeasure.KG,
     "65% Polyester 35% Cotton", "20s", None, None, Decimal("196.00"), Decimal("1000")),
    ("MAT-GRG-SJ", "Greige Single Jersey 180 GSM", MaterialCategory.GREIGE_FABRIC,
     UnitOfMeasure.KG, "100% Cotton", None, None, None, Decimal("310.00"), Decimal("800")),
    ("MAT-DYE-RB", "Reactive Blue HERD", MaterialCategory.DYE_CHEMICAL, UnitOfMeasure.KG,
     None, None, "Royal Blue", "RB-118", Decimal("1150.00"), Decimal("60")),
    ("MAT-DYE-BLK", "Reactive Black B 150%", MaterialCategory.DYE_CHEMICAL, UnitOfMeasure.KG,
     None, None, "Black", "BK-004", Decimal("980.00"), Decimal("80")),
    ("MAT-CHM-SOFT", "Silicone Softener KS-20", MaterialCategory.DYE_CHEMICAL,
     UnitOfMeasure.LITRE, None, None, None, None, Decimal("210.00"), Decimal("100")),
    ("MAT-PKG-POLY", "Polybag 250 x 350 mm", MaterialCategory.PACKAGING, UnitOfMeasure.PIECE,
     None, None, None, None, Decimal("1.40"), Decimal("5000")),
    ("MAT-PKG-CTN", "Export Carton 5-ply", MaterialCategory.PACKAGING, UnitOfMeasure.PIECE,
     None, None, None, None, Decimal("62.00"), Decimal("400")),
]

FABRIC_SPECS = [
    # code, name, composition, construction, gsm, width_cm, colour, shade, finish,
    # sale_unit, cost, lead_days
    ("FS-SJ180-WHT", "Single Jersey 180 GSM White", "100% Cotton", "40s / 24G",
     Decimal("180"), Decimal("165"), "Optic White", "WHT-000", FabricFinish.MERCERISED,
     UnitOfMeasure.METRE, Decimal("128.00"), 10),
    ("FS-SJ180-NVY", "Single Jersey 180 GSM Navy", "100% Cotton", "40s / 24G",
     Decimal("180"), Decimal("165"), "Navy", "NVY-419", FabricFinish.MERCERISED,
     UnitOfMeasure.METRE, Decimal("142.00"), 12),
    ("FS-INT200-RB", "Interlock 200 GSM Royal Blue", "100% Cotton", "30s / 24G",
     Decimal("200"), Decimal("180"), "Royal Blue", "RB-118", FabricFinish.PEACH,
     # Sold in yards: this customer orders in yards, and TextileOps never
     # silently treats a yard as a metre.
     UnitOfMeasure.YARD, Decimal("161.00"), 14),
    ("FS-PIQ220-BLK", "Pique 220 GSM Black", "100% Cotton", "30s / 20G",
     Decimal("220"), Decimal("170"), "Black", "BK-004", FabricFinish.ENZYME_WASH,
     # Sold by weight, as pique often is.
     UnitOfMeasure.KG, Decimal("398.00"), 14),
    ("FS-RIB240-WHT", "1x1 Rib 240 GSM White", "95% Cotton 5% Elastane", "30s + 40D / 18G",
     Decimal("240"), Decimal("90"), "Optic White", "WHT-000", FabricFinish.NONE,
     UnitOfMeasure.METRE, Decimal("176.00"), 9),
    ("FS-SJ160-PC", "Poly-Cotton Single Jersey 160 GSM", "65% Polyester 35% Cotton",
     "20s / 24G", Decimal("160"), Decimal("175"), "Melange Grey", "GRY-220",
     FabricFinish.CALENDERED, UnitOfMeasure.KG, Decimal("218.00"), 8),
]

#: Bill of materials: (fabric_code, material_code, qty per one sale unit, unit, wastage)
#:
#: Yarn consumption is derived from the real relationship
#: ``kg per metre = width_m × gsm ÷ 1000`` and then rounded to how the mill
#: actually books it. Dye and chemical dosages are per kg of fabric converted
#: to the fabric's sale unit.
BOM = [
    ("FS-SJ180-WHT", "MAT-YRN-40S", Decimal("0.297"), UnitOfMeasure.KG, Decimal("0.05")),
    ("FS-SJ180-WHT", "MAT-CHM-SOFT", Decimal("0.006"), UnitOfMeasure.LITRE, Decimal("0.02")),
    ("FS-SJ180-NVY", "MAT-YRN-40S", Decimal("0.297"), UnitOfMeasure.KG, Decimal("0.05")),
    ("FS-SJ180-NVY", "MAT-DYE-RB", Decimal("0.009"), UnitOfMeasure.KG, Decimal("0.03")),
    ("FS-SJ180-NVY", "MAT-CHM-SOFT", Decimal("0.006"), UnitOfMeasure.LITRE, Decimal("0.02")),
    # 200 GSM × 1.80 m = 0.360 kg per metre = 0.329 kg per yard.
    ("FS-INT200-RB", "MAT-YRN-30S", Decimal("0.329"), UnitOfMeasure.KG, Decimal("0.06")),
    ("FS-INT200-RB", "MAT-DYE-RB", Decimal("0.011"), UnitOfMeasure.KG, Decimal("0.03")),
    # Sold by weight: 1 kg of fabric needs ~1.08 kg of yarn after process loss.
    ("FS-PIQ220-BLK", "MAT-YRN-30S", Decimal("1.080"), UnitOfMeasure.KG, Decimal("0.04")),
    ("FS-PIQ220-BLK", "MAT-DYE-BLK", Decimal("0.045"), UnitOfMeasure.KG, Decimal("0.03")),
    ("FS-RIB240-WHT", "MAT-YRN-30S", Decimal("0.216"), UnitOfMeasure.KG, Decimal("0.05")),
    ("FS-SJ160-PC", "MAT-YRN-PC20", Decimal("1.070"), UnitOfMeasure.KG, Decimal("0.04")),
    ("FS-SJ160-PC", "MAT-CHM-SOFT", Decimal("0.008"), UnitOfMeasure.LITRE, Decimal("0.02")),
]
