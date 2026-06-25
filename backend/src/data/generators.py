"""Deterministic synthetic-data generators for the trade-agent demo.

These are the "configuration scripts" referenced throughout the docs: vendors and
HTS clauses are curated by hand for realism, and shipments are generated
deterministically (seeded RNG) so a seed run is reproducible. None of it is real.

Pure and side-effect-free: this module performs no I/O. The Firestore seed
(`scripts/seed_firestore.py`) and the Pinecone ingest (`scripts/ingest_kb.py`)
import these builders and handle persistence.
"""

import random

from src.models import (
    GoodsCategory,
    HtsClause,
    ManifestLineItem,
    RestrictionLevel,
    Shipment,
    ShipmentStatus,
    Vendor,
)

# Fixed seed so `build_shipments()` is reproducible across seed runs and tests.
DEFAULT_SEED: int = 20260601

# --- Curated vendor catalog ----------------------------------------------------
_VENDORS: tuple[Vendor, ...] = (
    Vendor(
        vendor_id="V-001",
        legal_name="Meridian Components LLC",
        country="Taiwan",
        customs_broker="Pacific Rim Customs Brokerage",
        categories=(GoodsCategory.ELECTRONICS,),
    ),
    Vendor(
        vendor_id="V-002",
        legal_name="Cascade Textile Imports Inc.",
        country="Vietnam",
        customs_broker="Harborline Trade Services",
        categories=(GoodsCategory.TEXTILES,),
    ),
    Vendor(
        vendor_id="V-003",
        legal_name="Golden Harvest Foods Co.",
        country="Mexico",
        customs_broker="Rio Grande Compliance Partners",
        categories=(GoodsCategory.AGRICULTURE,),
    ),
    Vendor(
        vendor_id="V-004",
        legal_name="Apex Industrial Machinery GmbH",
        country="Germany",
        customs_broker="Transatlantic Freight Compliance",
        categories=(GoodsCategory.MACHINERY,),
    ),
    Vendor(
        vendor_id="V-005",
        legal_name="BlueWave Pharma Distribution Ltd.",
        country="India",
        customs_broker="Meridian Regulatory Affairs",
        categories=(GoodsCategory.PHARMACEUTICALS, GoodsCategory.CHEMICALS),
    ),
)


# --- Curated HTS clause catalog (the shared, non-vendor-partitioned KB) ---------
_HTS_CLAUSES: tuple[HtsClause, ...] = (
    # Electronics — Chapters 84 / 85
    HtsClause(
        hts_code="8471.30.0100",
        chapter=84,
        heading="Automatic data-processing machines and units thereof",
        title="Portable digital computers, weighing under 10 kg",
        category=GoodsCategory.ELECTRONICS,
        duty_rate="Free",
        restriction=RestrictionLevel.UNRESTRICTED,
        description=(
            "Laptops, notebooks, and tablet computers weighing not more than 10 kg, "
            "comprising at least a central processing unit, a keyboard, and a display. "
            "Standard consumer information-technology goods admitted free of duty."
        ),
    ),
    HtsClause(
        hts_code="8517.13.0000",
        chapter=85,
        heading="Telephone sets and apparatus for communication",
        title="Smartphones",
        category=GoodsCategory.ELECTRONICS,
        duty_rate="Free",
        restriction=RestrictionLevel.UNRESTRICTED,
        description=(
            "Cellular telephones designed for a wireless network, incorporating a "
            "touchscreen and applications processor. Admitted free of duty as "
            "information-technology equipment."
        ),
    ),
    HtsClause(
        hts_code="8542.31.0001",
        chapter=85,
        heading="Electronic integrated circuits",
        title="Processors and controllers (microprocessor unit chips)",
        category=GoodsCategory.ELECTRONICS,
        duty_rate="Free",
        restriction=RestrictionLevel.LICENSE_REQUIRED,
        description=(
            "Monolithic digital integrated circuits functioning as processors or "
            "controllers. Although admitted free of duty, advanced computing and "
            "high-performance logic devices may fall under dual-use export-control "
            "classifications requiring an import/end-use license."
        ),
        notes="Verify dual-use ECCN classification and end-use license before clearance.",
    ),
    HtsClause(
        hts_code="8525.89.0000",
        chapter=85,
        heading="Television cameras, digital cameras and video recorders",
        title="High-resolution and thermal imaging cameras",
        category=GoodsCategory.ELECTRONICS,
        duty_rate="Free",
        restriction=RestrictionLevel.LICENSE_REQUIRED,
        description=(
            "Television and digital cameras, including units with thermal-imaging or "
            "high-frame-rate capability. Certain imaging performance thresholds trigger "
            "dual-use controls and require an import license."
        ),
        notes="Thermal/IR units above control thresholds require a license.",
    ),
    HtsClause(
        hts_code="8526.10.0040",
        chapter=85,
        heading="Radar apparatus, radio navigational aid and remote control",
        title="Radar apparatus",
        category=GoodsCategory.ELECTRONICS,
        duty_rate="Free",
        restriction=RestrictionLevel.LICENSE_REQUIRED,
        description=(
            "Radar transmitting/receiving apparatus. Controlled as potentially "
            "dual-use; an end-use statement and import license are required prior to "
            "release."
        ),
    ),
    # Textiles — Chapters 52 / 61 / 62 / 64
    HtsClause(
        hts_code="6109.10.0012",
        chapter=61,
        heading="T-shirts, singlets and other vests, knitted or crocheted",
        title="Men's or boys' cotton T-shirts, knitted",
        category=GoodsCategory.TEXTILES,
        duty_rate="16.5%",
        restriction=RestrictionLevel.QUOTA_CONTROLLED,
        description=(
            "Knitted cotton T-shirts and singlets. Subject to textile category limits; "
            "tariff-rate quota status must be verified against the current period's "
            "fill level before entry."
        ),
        notes="Confirm textile category 338/339 quota fill before clearance.",
    ),
    HtsClause(
        hts_code="6203.42.4011",
        chapter=62,
        heading="Men's or boys' suits, trousers and shorts, not knitted",
        title="Men's cotton trousers, not knitted",
        category=GoodsCategory.TEXTILES,
        duty_rate="16.6%",
        restriction=RestrictionLevel.QUOTA_CONTROLLED,
        description=(
            "Woven cotton trousers and breeches for men or boys. Quota-controlled "
            "textile category; visa and quota verification required."
        ),
    ),
    HtsClause(
        hts_code="5208.52.4055",
        chapter=52,
        heading="Woven fabrics of cotton, 85% or more by weight",
        title="Printed plain-weave cotton fabric",
        category=GoodsCategory.TEXTILES,
        duty_rate="11.4%",
        restriction=RestrictionLevel.UNRESTRICTED,
        description=(
            "Printed plain-weave fabrics of cotton, of yarns of different colors, "
            "weighing not more than 200 g/m². Standard dutiable textile entry."
        ),
    ),
    HtsClause(
        hts_code="6402.99.3165",
        chapter=64,
        heading="Footwear with outer soles and uppers of rubber or plastics",
        title="Footwear with rubber/plastic uppers",
        category=GoodsCategory.TEXTILES,
        duty_rate="6%",
        restriction=RestrictionLevel.UNRESTRICTED,
        description=(
            "Other footwear with outer soles and uppers of rubber or plastics, not "
            "covering the ankle. Standard dutiable consumer goods."
        ),
    ),
    # Agriculture — Chapters 02 / 08 / 09 / 16 / 20
    HtsClause(
        hts_code="0901.21.0030",
        chapter=9,
        heading="Coffee, whether or not roasted or decaffeinated",
        title="Roasted coffee, not decaffeinated",
        category=GoodsCategory.AGRICULTURE,
        duty_rate="Free",
        restriction=RestrictionLevel.UNRESTRICTED,
        description=(
            "Roasted coffee, not decaffeinated, in retail or bulk packing. Admitted "
            "free of duty; subject to standard FDA food-facility registration."
        ),
    ),
    HtsClause(
        hts_code="0803.90.0040",
        chapter=8,
        heading="Bananas and plantains, fresh or dried",
        title="Fresh bananas",
        category=GoodsCategory.AGRICULTURE,
        duty_rate="Free",
        restriction=RestrictionLevel.UNRESTRICTED,
        description=(
            "Fresh bananas of the Cavendish and similar varieties. Free of duty; "
            "subject to USDA-APHIS phytosanitary inspection on arrival."
        ),
    ),
    HtsClause(
        hts_code="2008.99.9190",
        chapter=20,
        heading="Fruit and other edible parts of plants, prepared or preserved",
        title="Prepared or preserved fruit, not elsewhere specified",
        category=GoodsCategory.AGRICULTURE,
        duty_rate="6%",
        restriction=RestrictionLevel.UNRESTRICTED,
        description=(
            "Prepared or preserved fruit and fruit mixtures not elsewhere specified, "
            "in airtight containers. Standard dutiable processed-food entry."
        ),
    ),
    HtsClause(
        hts_code="0207.14.0000",
        chapter=2,
        heading="Meat and edible offal of poultry, frozen",
        title="Frozen chicken cuts and offal",
        category=GoodsCategory.AGRICULTURE,
        duty_rate="17.6%",
        restriction=RestrictionLevel.LICENSE_REQUIRED,
        description=(
            "Frozen cuts and edible offal of chickens. Requires USDA-FSIS import "
            "eligibility from a certified establishment and an accompanying inspection "
            "certificate before release."
        ),
        notes="FSIS foreign-establishment eligibility and inspection certificate required.",
    ),
    HtsClause(
        hts_code="1604.14.1010",
        chapter=16,
        heading="Prepared or preserved fish; caviar",
        title="Prepared tuna, in airtight containers",
        category=GoodsCategory.AGRICULTURE,
        duty_rate="35%",
        restriction=RestrictionLevel.QUOTA_CONTROLLED,
        description=(
            "Tunas and skipjack, prepared or preserved in oil, in airtight containers. "
            "Subject to a tariff-rate quota; the higher over-quota rate applies once "
            "the annual quantity is reached."
        ),
        notes="Tariff-rate quota: confirm in-quota vs. over-quota rate at entry.",
    ),
    # Machinery — Chapter 84
    HtsClause(
        hts_code="8479.89.9499",
        chapter=84,
        heading="Machines and mechanical appliances having individual functions",
        title="Machines having individual functions, not elsewhere specified",
        category=GoodsCategory.MACHINERY,
        duty_rate="Free",
        restriction=RestrictionLevel.UNRESTRICTED,
        description=(
            "Mechanical appliances having individual functions, not specified or "
            "included elsewhere in Chapter 84. General industrial machinery admitted "
            "free of duty."
        ),
    ),
    HtsClause(
        hts_code="8413.70.2004",
        chapter=84,
        heading="Pumps for liquids; liquid elevators",
        title="Centrifugal pumps for liquids",
        category=GoodsCategory.MACHINERY,
        duty_rate="Free",
        restriction=RestrictionLevel.UNRESTRICTED,
        description=(
            "Submersible and other centrifugal pumps for liquids. General-purpose "
            "industrial pumps admitted free of duty."
        ),
    ),
    HtsClause(
        hts_code="8456.11.1000",
        chapter=84,
        heading="Machine tools operated by laser or other light/photon-beam processes",
        title="Laser-operated machine tools",
        category=GoodsCategory.MACHINERY,
        duty_rate="Free",
        restriction=RestrictionLevel.LICENSE_REQUIRED,
        description=(
            "Machine tools for working any material by removal, operated by laser. "
            "High-power laser systems are dual-use controlled; an end-use license is "
            "required before clearance."
        ),
        notes="High-power laser systems are dual-use; verify license before release.",
    ),
    HtsClause(
        hts_code="8421.39.8015",
        chapter=84,
        heading="Filtering or purifying machinery for gases",
        title="Gas filtering/purifying machinery and separators",
        category=GoodsCategory.MACHINERY,
        duty_rate="Free",
        restriction=RestrictionLevel.LICENSE_REQUIRED,
        description=(
            "Centrifugal separators and gas filtering/purifying machinery. Certain "
            "high-specification separators are controlled under nonproliferation "
            "regimes and require an import license and end-use verification."
        ),
        notes="High-spec separators are nonproliferation-controlled; license required.",
    ),
    # Pharmaceuticals — Chapter 30 / 29
    HtsClause(
        hts_code="3004.90.9228",
        chapter=30,
        heading="Medicaments put up in measured doses or for retail sale",
        title="Medicaments in dosage form, not elsewhere specified",
        category=GoodsCategory.PHARMACEUTICALS,
        duty_rate="Free",
        restriction=RestrictionLevel.LICENSE_REQUIRED,
        description=(
            "Mixed or unmixed medicaments put up in measured doses or retail packing. "
            "Requires a valid FDA registration/listing and entry review; release is "
            "conditioned on FDA admissibility."
        ),
        notes="FDA-regulated; entry subject to FDA review and may be detained without DAU.",
    ),
    HtsClause(
        hts_code="3002.15.0100",
        chapter=30,
        heading="Immunological products, put up in measured doses",
        title="Immunological products in dosage form",
        category=GoodsCategory.PHARMACEUTICALS,
        duty_rate="Free",
        restriction=RestrictionLevel.LICENSE_REQUIRED,
        description=(
            "Immunological products put up in measured doses or for retail sale. "
            "Subject to FDA biologics oversight; import requires applicable licensure "
            "and admissibility review."
        ),
    ),
    HtsClause(
        hts_code="2933.99.9700",
        chapter=29,
        heading="Heterocyclic compounds with nitrogen hetero-atom(s) only",
        title="Active pharmaceutical ingredients (heterocyclic compounds)",
        category=GoodsCategory.PHARMACEUTICALS,
        duty_rate="6.5%",
        restriction=RestrictionLevel.LICENSE_REQUIRED,
        description=(
            "Other heterocyclic compounds used as active pharmaceutical ingredients. "
            "Dutiable; FDA drug-establishment registration and ingredient review "
            "required before clearance."
        ),
    ),
    # Chemicals — Chapter 28 / 29
    HtsClause(
        hts_code="2811.19.6090",
        chapter=28,
        heading="Other inorganic acids and inorganic oxygen compounds",
        title="Inorganic acids, not elsewhere specified",
        category=GoodsCategory.CHEMICALS,
        duty_rate="3.7%",
        restriction=RestrictionLevel.LICENSE_REQUIRED,
        description=(
            "Other inorganic acids not elsewhere specified. Hazardous-material handling "
            "and an import license/permit are required; subject to EPA-TSCA and DOT "
            "documentation."
        ),
    ),
    HtsClause(
        hts_code="2914.11.0000",
        chapter=29,
        heading="Ketones and quinones",
        title="Acetone",
        category=GoodsCategory.CHEMICALS,
        duty_rate="5.5%",
        restriction=RestrictionLevel.UNRESTRICTED,
        description=(
            "Acetone (propan-2-one) in industrial grade. Dutiable industrial solvent; "
            "standard TSCA inventory compliance applies."
        ),
    ),
    HtsClause(
        hts_code="2939.41.0000",
        chapter=29,
        heading="Alkaloids of vegetable origin and their salts",
        title="Ephedrine and its salts (List I chemical precursor)",
        category=GoodsCategory.CHEMICALS,
        duty_rate="Free",
        restriction=RestrictionLevel.PROHIBITED,
        description=(
            "Ephedrine and its salts — a regulated List I chemical precursor. Not "
            "admissible without a valid DEA importer registration and an approved "
            "import permit; absent authorization the entry is refused."
        ),
        notes="DEA List I precursor: refuse entry absent registration and import permit.",
    ),
)

# Reference ports/carriers used to dress up generated shipments.
_ORIGIN_PORTS: tuple[str, ...] = (
    "Kaohsiung, TW",
    "Ho Chi Minh City, VN",
    "Manzanillo, MX",
    "Hamburg, DE",
    "Nhava Sheva, IN",
    "Shenzhen, CN",
)
_DESTINATION_PORTS: tuple[str, ...] = (
    "Los Angeles, US",
    "Long Beach, US",
    "Newark, US",
    "Savannah, US",
    "Houston, US",
)
_CARRIERS: tuple[str, ...] = (
    "Evergreen Marine",
    "Maersk Line",
    "CMA CGM",
    "Hapag-Lloyd",
    "ONE Network Express",
)
_UNITS: tuple[str, ...] = ("cartons", "pallets", "units", "drums", "rolls")

# Statuses a *clean* (unrestricted) shipment may land on.
_CLEAN_STATUSES: tuple[ShipmentStatus, ...] = (
    ShipmentStatus.IN_TRANSIT,
    ShipmentStatus.CLEARED,
)


def build_vendors() -> tuple[Vendor, ...]:
    """Return the curated vendor catalog."""
    return _VENDORS


def build_hts_clauses() -> tuple[HtsClause, ...]:
    """Return the curated HTS clause catalog (the shared KB corpus)."""
    return _HTS_CLAUSES


def _flag_reason(line: ManifestLineItem, restriction: RestrictionLevel) -> str | None:
    """Map a restricted manifest line to a human-readable hold reason."""
    if restriction is RestrictionLevel.LICENSE_REQUIRED:
        return (
            f"Manifest line {line.line_no} (HTS {line.hts_code}) requires an import "
            f"license; supporting documentation is not attached to the entry."
        )
    if restriction is RestrictionLevel.QUOTA_CONTROLLED:
        return (
            f"Manifest line {line.line_no} (HTS {line.hts_code}) is quota-controlled; "
            f"tariff-rate quota status is pending verification."
        )
    if restriction is RestrictionLevel.PROHIBITED:
        return (
            f"Manifest line {line.line_no} (HTS {line.hts_code}) flagged: regulated "
            f"precursor requiring import authorization absent from the entry."
        )
    return None


def build_shipments(seed: int = DEFAULT_SEED) -> tuple[Shipment, ...]:
    """Generate a deterministic, vendor-scoped set of synthetic shipments.

    Each shipment references only HTS clauses inside its vendor's category scope.
    Shipments whose manifest contains a restricted line are deterministically
    routed to HELD/FLAGGED with a matching ``flag_reason``; clean shipments land
    IN_TRANSIT or CLEARED. The same ``seed`` always yields the same output.
    """
    rng = random.Random(seed)
    clauses_by_category: dict[GoodsCategory, list[HtsClause]] = {}
    for clause in _HTS_CLAUSES:
        clauses_by_category.setdefault(clause.category, []).append(clause)
    restriction_by_code: dict[str, RestrictionLevel] = {
        c.hts_code: c.restriction for c in _HTS_CLAUSES
    }

    shipments: list[Shipment] = []
    next_id = 1001
    for vendor in _VENDORS:
        for _ in range(rng.randint(4, 6)):
            category = rng.choice(vendor.categories)
            pool = clauses_by_category[category]
            line_count = rng.randint(1, min(3, len(pool)))
            chosen = rng.sample(pool, line_count)

            manifest: list[ManifestLineItem] = []
            for line_no, clause in enumerate(chosen, start=1):
                quantity = rng.randint(20, 5000)
                unit_value = round(rng.uniform(8.0, 1200.0), 2)
                manifest.append(
                    ManifestLineItem(
                        line_no=line_no,
                        description=clause.title,
                        hts_code=clause.hts_code,
                        quantity=quantity,
                        unit=rng.choice(_UNITS),
                        declared_value_usd=round(quantity * unit_value, 2),
                        country_of_origin=vendor.country,
                    )
                )

            # Status + flag reason are driven by the most severe restricted line.
            status = rng.choice(_CLEAN_STATUSES)
            flag_reason: str | None = None
            for line in manifest:
                restriction = restriction_by_code[line.hts_code]
                reason = _flag_reason(line, restriction)
                if reason is not None:
                    status = (
                        ShipmentStatus.FLAGGED
                        if restriction is RestrictionLevel.PROHIBITED
                        else rng.choice((ShipmentStatus.HELD, ShipmentStatus.FLAGGED))
                    )
                    flag_reason = reason
                    break

            shipment_id = f"S-{next_id}"
            next_id += 1
            eta_day = rng.randint(1, 28)
            shipments.append(
                Shipment(
                    shipment_id=shipment_id,
                    vendor_id=vendor.vendor_id,
                    bill_of_lading=f"BOL-{rng.randint(100000, 999999)}",
                    carrier=rng.choice(_CARRIERS),
                    container_id=f"TRDU{rng.randint(1000000, 9999999)}",
                    origin_port=rng.choice(_ORIGIN_PORTS),
                    destination_port=rng.choice(_DESTINATION_PORTS),
                    eta=f"2026-07-{eta_day:02d}",
                    status=status,
                    flag_reason=flag_reason,
                    manifest=tuple(manifest),
                )
            )

    return tuple(shipments)
