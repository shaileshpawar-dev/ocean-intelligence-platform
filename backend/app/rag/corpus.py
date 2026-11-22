"""Seed corpus for the research assistant.

Sourcing policy
---------------
Fabricating a plausible-looking bibliography would be the single fastest way
to destroy this project's credibility, so this corpus contains only two kinds
of document, and each is labelled:

* ``regulation`` -- real, named international instruments. Titles, adopting
  bodies, adoption/entry-into-force years and scope are factual. The body text
  is a **platform-authored scope summary**, not verbatim treaty text, and each
  record says so. ``source_url`` points at the *organisation* that maintains
  the instrument rather than a deep link, because a stale deep link is worse
  than none.

* ``reference`` -- platform-authored technical notes describing this system's
  own methodology and the physics it relies on. These are attributed to the
  platform, not to any external author.

There are deliberately **no invented journal papers**. Adding real literature
is an ingestion task, not a seeding task: point
:func:`app.rag.service.ingest_document` at a real corpus and it will be
retrievable alongside these.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SUMMARY_NOTICE = (
    "Scope summary authored by the Ocean Intelligence Platform for retrieval "
    "purposes. Not verbatim text of the instrument. Consult the official "
    "source before relying on this for any legal or compliance purpose."
)

METHOD_NOTICE = (
    "Technical note authored by the Ocean Intelligence Platform describing its "
    "own methodology. Not an external publication."
)


@dataclass(slots=True)
class SeedDocument:
    """One document in the seed corpus."""

    document_id: str
    title: str
    doc_type: str  # regulation | reference
    text: str
    year: int | None = None
    publication: str | None = None
    authors: str | None = None
    jurisdiction: str | None = None
    source_url: str | None = None
    regions: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    notice: str = SUMMARY_NOTICE


REGULATIONS: tuple[SeedDocument, ...] = (
    SeedDocument(
        document_id="marpol-annex-i",
        title="MARPOL 73/78 Annex I — Regulations for the Prevention of Pollution by Oil",
        doc_type="regulation",
        year=1983,
        publication="International Maritime Organization",
        jurisdiction="International",
        source_url="https://www.imo.org",
        topics=["oil", "discharge", "shipping", "operational pollution"],
        text=(
            "Annex I of the International Convention for the Prevention of "
            "Pollution from Ships (MARPOL 73/78) governs pollution by oil from "
            "ships. It entered into force on 2 October 1983. It restricts "
            "operational discharges of oil and oily mixtures, sets discharge "
            "criteria including an oil content limit for permitted effluent, "
            "designates Special Areas where discharge restrictions are "
            "stricter, and requires tankers and larger vessels to maintain an "
            "Oil Record Book and carry a Shipboard Oil Pollution Emergency "
            "Plan (SOPEP). Special Areas designated under Annex I include the "
            "Mediterranean Sea, the Baltic Sea, the Black Sea, the Red Sea, "
            "the Gulfs area, the Gulf of Aden, Antarctic waters, North West "
            "European waters, the Oman area of the Arabian Sea, and Southern "
            "South African waters. A dark formation detected near a shipping "
            "lane may indicate an operational discharge falling under this "
            "Annex, but a satellite detection alone does not establish a "
            "violation: attribution requires vessel identification and, "
            "normally, sampling."
        ),
    ),
    SeedDocument(
        document_id="marpol-annex-v",
        title="MARPOL 73/78 Annex V — Prevention of Pollution by Garbage from Ships",
        doc_type="regulation",
        year=1988,
        publication="International Maritime Organization",
        jurisdiction="International",
        source_url="https://www.imo.org",
        topics=["plastic", "garbage", "debris", "shipping"],
        text=(
            "Annex V of MARPOL regulates garbage from ships. It prohibits the "
            "discharge of all plastics into the sea anywhere, without "
            "exception, and restricts the discharge of other categories of "
            "garbage by distance from land and by area. Revised requirements "
            "adopted in 2011 shifted the regime from listing what may not be "
            "discharged to prohibiting discharge of everything except a short "
            "permitted list. Garbage Record Books and garbage management plans "
            "are required for vessels above specified sizes. This Annex is the "
            "relevant instrument where floating debris is observed, though "
            "optical satellite detection of marine debris carries high "
            "uncertainty and cannot by itself attribute material to a vessel."
        ),
    ),
    SeedDocument(
        document_id="oprc-1990",
        title=(
            "International Convention on Oil Pollution Preparedness, Response "
            "and Co-operation (OPRC 1990)"
        ),
        doc_type="regulation",
        year=1995,
        publication="International Maritime Organization",
        jurisdiction="International",
        source_url="https://www.imo.org",
        topics=["oil spill", "response", "preparedness", "reporting"],
        text=(
            "OPRC was adopted in 1990 and entered into force in 1995. It "
            "obliges Parties to establish national systems for responding to "
            "oil pollution incidents, including a national contingency plan "
            "and designated competent authorities. Ships and offshore units "
            "must carry oil pollution emergency plans. The Convention "
            "establishes duties to report observed oil pollution incidents and "
            "provides a framework for international co-operation and mutual "
            "assistance in major incidents. It is the instrument that makes an "
            "observation actionable: a credible detection of an oil-like "
            "signature is the kind of information a national contingency "
            "system exists to receive and verify."
        ),
    ),
    SeedDocument(
        document_id="unclos-part-xii",
        title=(
            "UNCLOS Part XII — Protection and Preservation of the Marine "
            "Environment (Articles 192-237)"
        ),
        doc_type="regulation",
        year=1994,
        publication="United Nations",
        jurisdiction="International",
        source_url="https://www.un.org/depts/los/",
        topics=["marine environment", "state obligations", "jurisdiction"],
        text=(
            "Part XII of the United Nations Convention on the Law of the Sea "
            "establishes the general legal framework for protecting the marine "
            "environment. Article 192 states the general obligation of States "
            "to protect and preserve the marine environment. Article 194 "
            "requires States to take measures to prevent, reduce and control "
            "pollution of the marine environment from any source, using the "
            "best practicable means at their disposal. Further articles "
            "address pollution from land-based sources, seabed activities, "
            "dumping, vessels and the atmosphere, and allocate enforcement "
            "jurisdiction between flag, port and coastal States. UNCLOS "
            "entered into force in 1994 and is the umbrella under which the "
            "more specific IMO instruments operate."
        ),
    ),
    SeedDocument(
        document_id="clc-1992",
        title=(
            "International Convention on Civil Liability for Oil Pollution "
            "Damage (CLC 1992)"
        ),
        doc_type="regulation",
        year=1996,
        publication="International Maritime Organization",
        jurisdiction="International",
        source_url="https://www.imo.org",
        topics=["liability", "compensation", "oil", "tankers"],
        text=(
            "The 1992 Civil Liability Convention establishes strict liability "
            "of the registered shipowner for pollution damage caused by "
            "persistent oil escaping from a laden tanker, subject to limits "
            "based on tonnage and to compulsory insurance. It works alongside "
            "the 1992 Fund Convention, which provides supplementary "
            "compensation where the shipowner's liability is insufficient or "
            "unavailable. Together they determine who pays for damage from a "
            "tanker oil spill. They apply to persistent oil from tankers; "
            "bunker oil from non-tankers is covered separately by the 2001 "
            "Bunkers Convention."
        ),
    ),
    SeedDocument(
        document_id="bunkers-2001",
        title=(
            "International Convention on Civil Liability for Bunker Oil "
            "Pollution Damage (Bunkers Convention 2001)"
        ),
        doc_type="regulation",
        year=2008,
        publication="International Maritime Organization",
        jurisdiction="International",
        source_url="https://www.imo.org",
        topics=["liability", "bunker fuel", "compensation"],
        text=(
            "The Bunkers Convention, adopted in 2001 and in force from 2008, "
            "provides for liability and compensation for pollution damage "
            "caused by spills of bunker oil — the fuel carried by ships for "
            "their own propulsion — from vessels other than tankers carrying "
            "oil as cargo. It imposes strict liability on the shipowner and "
            "requires compulsory insurance for vessels above a specified "
            "tonnage. It closes the gap left by the CLC regime, which covers "
            "only persistent cargo oil from tankers."
        ),
    ),
    SeedDocument(
        document_id="london-protocol",
        title="London Convention 1972 and London Protocol 1996 — Dumping at Sea",
        doc_type="regulation",
        year=2006,
        publication="International Maritime Organization",
        jurisdiction="International",
        source_url="https://www.imo.org",
        topics=["dumping", "waste", "chemical"],
        text=(
            "The London Convention (1972) and its 1996 Protocol regulate the "
            "deliberate disposal of wastes at sea. The Protocol, in force from "
            "2006, reverses the Convention's logic: rather than listing "
            "prohibited substances, it prohibits all dumping except for a "
            "short reverse list of permitted materials, and it incorporates "
            "the precautionary approach and the polluter-pays principle. It is "
            "the relevant instrument for deliberate discharge of waste "
            "material as distinct from operational discharge from ships, which "
            "falls under MARPOL."
        ),
    ),
    SeedDocument(
        document_id="eu-2005-35-ec",
        title=(
            "Directive 2005/35/EC on Ship-Source Pollution and Penalties "
            "for Infringements"
        ),
        doc_type="regulation",
        year=2005,
        publication="European Union",
        jurisdiction="European Union",
        source_url="https://eur-lex.europa.eu",
        regions=["Mediterranean", "North Sea", "Baltic Sea"],
        topics=["enforcement", "penalties", "oil", "ship-source"],
        text=(
            "Directive 2005/35/EC incorporates international discharge "
            "standards for ship-source pollution into European Union law and "
            "requires Member States to impose effective, proportionate and "
            "dissuasive penalties, including criminal penalties, for "
            "infringements committed with intent, recklessly or by serious "
            "negligence. It applies to discharges of oil and noxious liquid "
            "substances and covers discharges in internal waters, territorial "
            "sea, straits used for international navigation, exclusive "
            "economic zones and the high seas. It is the legal backdrop to "
            "EMSA's satellite surveillance activity in European waters."
        ),
    ),
    SeedDocument(
        document_id="ospar-convention",
        title=(
            "OSPAR Convention — Protection of the Marine Environment of the "
            "North-East Atlantic"
        ),
        doc_type="regulation",
        year=1998,
        publication="OSPAR Commission",
        jurisdiction="North-East Atlantic",
        source_url="https://www.ospar.org",
        regions=["North Sea"],
        topics=["regional seas", "offshore", "monitoring"],
        text=(
            "The OSPAR Convention governs international co-operation on "
            "protection of the marine environment of the North-East Atlantic, "
            "including the North Sea. It entered into force in 1998, uniting "
            "and updating the earlier Oslo and Paris Conventions. Its annexes "
            "address pollution from land-based sources, dumping and "
            "incineration, offshore oil and gas installations, assessment of "
            "environmental quality, and biodiversity and ecosystems. OSPAR "
            "co-ordinates monitoring programmes and maintains an aerial and "
            "satellite surveillance regime for oil discharges in the region."
        ),
    ),
    SeedDocument(
        document_id="helcom-convention",
        title="Helsinki Convention (HELCOM) — Protection of the Baltic Sea Area",
        doc_type="regulation",
        year=2000,
        publication="Baltic Marine Environment Protection Commission",
        jurisdiction="Baltic Sea",
        source_url="https://helcom.fi",
        topics=["regional seas", "monitoring", "eutrophication"],
        text=(
            "The Convention on the Protection of the Marine Environment of the "
            "Baltic Sea Area, administered by HELCOM, addresses pollution of "
            "the Baltic from all sources. The Baltic is a MARPOL Special Area "
            "with stricter discharge rules reflecting its shallow, "
            "semi-enclosed character and slow water exchange. HELCOM "
            "co-ordinates regular aerial surveillance for illegal discharges "
            "and maintains regional response co-operation, and its work "
            "programme gives substantial attention to eutrophication and algal "
            "blooms alongside oil pollution."
        ),
    ),
    SeedDocument(
        document_id="barcelona-convention",
        title="Barcelona Convention and UNEP Mediterranean Action Plan",
        doc_type="regulation",
        year=1978,
        publication="United Nations Environment Programme",
        jurisdiction="Mediterranean",
        source_url="https://www.unep.org/unepmap/",
        regions=["Mediterranean"],
        topics=["regional seas", "oil", "protected areas"],
        text=(
            "The Convention for the Protection of the Marine Environment and "
            "the Coastal Region of the Mediterranean, adopted at Barcelona in "
            "1976 and substantially amended in 1995, is the legal framework of "
            "the UNEP Mediterranean Action Plan. Its protocols cover dumping, "
            "prevention and emergency response to pollution from ships, "
            "land-based sources, specially protected areas and biological "
            "diversity, offshore activities, hazardous wastes and integrated "
            "coastal zone management. REMPEC, based in Malta, supports "
            "regional preparedness and response to marine pollution incidents. "
            "The Mediterranean is a MARPOL Annex I Special Area."
        ),
    ),
    SeedDocument(
        document_id="kuwait-convention-ropme",
        title="Kuwait Regional Convention (ROPME Sea Area)",
        doc_type="regulation",
        year=1979,
        publication="Regional Organization for the Protection of the Marine Environment",
        jurisdiction="Persian Gulf / ROPME Sea Area",
        source_url="https://ropme.org",
        regions=["Persian Gulf", "Arabian Sea"],
        topics=["regional seas", "oil", "response"],
        text=(
            "The Kuwait Regional Convention for Co-operation on the Protection "
            "of the Marine Environment from Pollution, adopted in 1978, covers "
            "the ROPME Sea Area encompassing the Persian Gulf, the Strait of "
            "Hormuz and the Gulf of Oman. It is administered by ROPME, with "
            "the Marine Emergency Mutual Aid Centre (MEMAC) supporting "
            "regional response to oil pollution emergencies. The area carries "
            "an exceptionally high density of tanker traffic and offshore "
            "petroleum infrastructure, and is designated a MARPOL Special "
            "Area, making it one of the most closely regulated bodies of water "
            "for oil discharge anywhere."
        ),
    ),
    SeedDocument(
        document_id="abidjan-convention",
        title="Abidjan Convention — West, Central and Southern African Atlantic Coast",
        doc_type="regulation",
        year=1984,
        publication="United Nations Environment Programme",
        jurisdiction="West and Central Africa",
        source_url="https://www.unep.org",
        regions=["Gulf of Guinea"],
        topics=["regional seas", "oil", "offshore"],
        text=(
            "The Convention for Co-operation in the Protection, Management and "
            "Development of the Marine and Coastal Environment of the Atlantic "
            "Coast of the West, Central and Southern Africa Region, adopted at "
            "Abidjan in 1981, entered into force in 1984. It addresses "
            "pollution from ships, dumping, land-based sources, seabed "
            "activities and coastal erosion across a region that includes the "
            "Gulf of Guinea, an area of substantial offshore oil production "
            "and associated pollution risk."
        ),
    ),
    SeedDocument(
        document_id="nairobi-convention",
        title="Nairobi Convention — Western Indian Ocean",
        doc_type="regulation",
        year=1996,
        publication="United Nations Environment Programme",
        jurisdiction="Western Indian Ocean",
        source_url="https://www.unep.org",
        regions=["Arabian Sea", "Red Sea"],
        topics=["regional seas", "protected areas", "biodiversity"],
        text=(
            "The Convention for the Protection, Management and Development of "
            "the Marine and Coastal Environment of the Western Indian Ocean, "
            "adopted at Nairobi in 1985, provides the regional framework for "
            "co-operation among Eastern and Southern African states and island "
            "states. Its protocols cover protected areas and wild fauna and "
            "flora, co-operation in combating pollution in cases of emergency, "
            "and land-based sources and activities. The region contains "
            "extensive coral reef systems and several World Heritage marine "
            "sites, raising the environmental stakes of pollution events."
        ),
    ),
)


REFERENCES: tuple[SeedDocument, ...] = (
    SeedDocument(
        document_id="oip-sar-methodology",
        title="Dark-Formation Detection in C-band SAR: Method and Limits",
        doc_type="reference",
        publication="Ocean Intelligence Platform",
        authors="Ocean Intelligence Platform",
        topics=["SAR", "detection", "methodology", "oil"],
        notice=METHOD_NOTICE,
        text=(
            "Sentinel-1 carries a C-band synthetic aperture radar operating at "
            "5.405 GHz. Over water the dominant return mechanism is Bragg "
            "scattering from short gravity-capillary waves at centimetre "
            "scale. A surface film raises surface tension and damps those "
            "waves, reducing backscatter and producing a region of anomalously "
            "low return known as a dark formation. Dark-formation detection is "
            "the accepted first stage of operational SAR oil-spill services. "
            "The measured quantity is surface roughness, not composition: "
            "C-band VV backscatter cannot identify a substance, cannot measure "
            "film thickness reliably because backscatter saturates, and cannot "
            "see dissolved or sub-surface material at all. This platform "
            "therefore reports an oil-like signature rather than an oil spill, "
            "and attaches look-alike caveats to every positive detection."
        ),
    ),
    SeedDocument(
        document_id="oip-lookalikes",
        title="Oil-Spill Look-alikes in SAR Imagery",
        doc_type="reference",
        publication="Ocean Intelligence Platform",
        authors="Ocean Intelligence Platform",
        topics=["SAR", "false positives", "wind", "biogenic"],
        notice=METHOD_NOTICE,
        text=(
            "Several phenomena produce dark formations indistinguishable from "
            "mineral oil in single-polarisation C-band imagery. Low wind is "
            "the most common: below roughly 3 metres per second the sea "
            "surface carries too few capillary waves to scatter from, so the "
            "whole area appears dark. Biogenic slicks from algal exudates damp "
            "waves by the same physical mechanism as oil. Rain cells attenuate "
            "the signal and disturb the surface. Wind shadows form in the lee "
            "of land or under orographic effects. Grease ice damps the surface "
            "at high latitude. Upwelling and current shear can locally "
            "suppress the wave field. The discriminating feature this platform "
            "uses is structure: a slick is a dark patch inside a "
            "normally-scattering sea, whereas a low-wind zone is dark "
            "throughout. Uniformly dark cells are therefore reported as bare "
            "dark formations with low confidence, not as oil-like signatures. "
            "Wind speed, where available, is the single most informative "
            "additional variable for resolving these cases."
        ),
    ),
    SeedDocument(
        document_id="oip-risk-methodology",
        title="Deterministic Environmental Risk Scoring: Factors and Renormalisation",
        doc_type="reference",
        publication="Ocean Intelligence Platform",
        authors="Ocean Intelligence Platform",
        topics=["risk", "methodology", "explainability"],
        notice=METHOD_NOTICE,
        text=(
            "This platform computes environmental risk arithmetically, never "
            "with a language model. Six factors contribute: signature "
            "severity, detection confidence, affected area on a logarithmic "
            "scale, proximity to coastline, proximity to a marine protected "
            "area, and the regional historical trend. Each returns points "
            "against a documented maximum, and the contributions sum exactly "
            "to the reported score, so any assessment can be reconstructed "
            "from its parts. Where a factor cannot be evaluated because its "
            "input is missing, that factor is dropped and the score is "
            "renormalised over the factors that were evaluable, with the "
            "omission listed explicitly. Treating unknown inputs as zero would "
            "make an unmeasured event appear safe, which is the more dangerous "
            "failure direction. The weights are a documented product "
            "judgement, not a physical constant, and are versioned so a stored "
            "assessment always traces to the weighting that produced it."
        ),
    ),
    SeedDocument(
        document_id="oip-forecast-scope",
        title="Forecast Scope: Detection Activity versus Physical Dispersion",
        doc_type="reference",
        publication="Ocean Intelligence Platform",
        authors="Ocean Intelligence Platform",
        topics=["forecasting", "limitations", "dispersion"],
        notice=METHOD_NOTICE,
        text=(
            "This platform forecasts detection activity — the trend in its own "
            "risk scores and event counts for a region — and labels every "
            "forecast accordingly. It does not forecast where a pollutant will "
            "physically travel. Dispersion modelling requires surface "
            "currents, wind fields, wave spectra, oil type and weathering "
            "state, integrated in a Lagrangian particle-transport model such "
            "as GNOME, OpenDrift or MEDSLIK. None of those inputs are ingested "
            "here. A forecast of detection activity is a monitoring signal: it "
            "answers whether a region is trending worse, which is worth an "
            "analyst's attention, but it moves if satellite coverage or a "
            "detection threshold changes even when nothing changes in the "
            "water. Every forecast is backtested against a naive last-value "
            "baseline and reports whether it beat it."
        ),
    ),
    SeedDocument(
        document_id="oip-satellite-monitoring",
        title="Operational Satellite Monitoring of Marine Oil Pollution",
        doc_type="reference",
        publication="Ocean Intelligence Platform",
        authors="Ocean Intelligence Platform",
        topics=["monitoring", "Sentinel-1", "operational", "CleanSeaNet"],
        notice=METHOD_NOTICE,
        text=(
            "Operational marine pollution surveillance combines satellite "
            "detection with verification. The European Maritime Safety Agency "
            "operates CleanSeaNet, a European satellite-based oil spill and "
            "vessel detection service that delivers alerts to coastal states "
            "for follow-up by aerial or vessel inspection. The Copernicus "
            "Sentinel-1 mission provides C-band SAR imagery with wide-swath "
            "coverage and regular revisit, and is the primary free data source "
            "for this class of monitoring. The operational pattern is "
            "screen-wide-then-confirm-narrow: cheap coverage of large areas "
            "identifies candidates, and expensive high-resolution or in-situ "
            "verification confirms them. Satellite detection alone is a "
            "trigger for investigation, not evidence of a violation; "
            "attribution to a vessel normally requires correlation with AIS "
            "tracks and, for enforcement, physical sampling."
        ),
    ),
)


# ---------------------------------------------------------------------------
# India water quality
#
# Summaries of the two CPCB documents the water status engine actually applies,
# plus the platform's own note on how it handles data age. The numeric
# thresholds quoted here were verified against the CPCB criteria before being
# written, and are the same values app/water/standards.py enforces -- so a
# retrieved passage and a computed status cannot disagree.
# ---------------------------------------------------------------------------
WATER_DOCUMENTS: tuple[SeedDocument, ...] = (
    SeedDocument(
        document_id="cpcb-designated-best-use",
        title="CPCB Designated Best Use Water Quality Criteria (Classes A-E)",
        doc_type="regulation",
        publication="Central Pollution Control Board, India",
        jurisdiction="India",
        source_url=(
            "https://cpcb.nic.in/wqm/Designated_Best_Use_Water_Quality_Criteria.pdf"
        ),
        regions=["india"],
        topics=["water quality", "standards", "rivers", "bod", "dissolved oxygen"],
        text=(
            "CPCB classifies inland surface water by its designated best use, "
            "because whether water is polluted depends on what it is used for. "
            "Class A, drinking water source without conventional treatment but "
            "after disinfection: total coliform 50 MPN/100mL or less, pH 6.5 to "
            "8.5, dissolved oxygen 6 mg/L or more, biochemical oxygen demand "
            "(BOD) 2 mg/L or less. Class B, organised outdoor bathing: total "
            "coliform 500 MPN/100mL or less, pH 6.5 to 8.5, dissolved oxygen 5 "
            "mg/L or more, BOD 3 mg/L or less. Class C, drinking water source "
            "after conventional treatment and disinfection: total coliform 5000 "
            "MPN/100mL or less, pH 6 to 9, dissolved oxygen 4 mg/L or more, BOD "
            "3 mg/L or less. Class D, propagation of wildlife and fisheries: pH "
            "6.5 to 8.5, dissolved oxygen 4 mg/L or more, free ammonia as N 1.2 "
            "mg/L or less. Class E, irrigation, industrial cooling and "
            "controlled waste disposal: pH 6.0 to 8.5, electrical conductivity "
            "at most 2250 micromhos/cm, sodium adsorption ratio at most 26, "
            "boron at most 2 mg/L. A parameter a class does not list has no "
            "limit under that class. Low dissolved oxygen is harmful, so for "
            "dissolved oxygen the criterion is a minimum rather than a maximum."
        ),
    ),
    SeedDocument(
        document_id="cpcb-polluted-river-stretches",
        title="CPCB Polluted River Stretches: Identification Criteria and Priority",
        doc_type="regulation",
        publication="Central Pollution Control Board, India",
        jurisdiction="India",
        source_url="https://cpcb.nic.in/wqm/RS-criteria-status.pdf",
        regions=["india"],
        topics=["polluted river stretch", "bod", "priority", "rivers"],
        text=(
            "CPCB identifies polluted river stretches using biochemical oxygen "
            "demand. A monitoring location where BOD exceeds 3 mg/L, the limit "
            "for outdoor bathing, is treated as polluted. Two or more polluted "
            "locations in continuous sequence on the same river are defined as "
            "a Polluted River Stretch. Stretches are ranked into five priority "
            "classes by BOD: Priority I, BOD above 30 mg/L; Priority II, 20 to "
            "30 mg/L; Priority III, 10 to 20 mg/L; Priority IV, 6 to 10 mg/L; "
            "Priority V, 3 to 6 mg/L. Priority I stretches need the most urgent "
            "intervention. The classification is based on monitored BOD and "
            "says nothing directly about other pollutants such as heavy metals."
        ),
    ),
    SeedDocument(
        document_id="oip-water-freshness-methodology",
        title="How This Platform Handles Data Age and Water Status",
        doc_type="reference",
        publication="OceanAI methodology note",
        regions=["india"],
        topics=["freshness", "methodology", "status", "data age"],
        notice=METHOD_NOTICE,
        text=(
            "The platform never describes a water body as currently polluted or "
            "currently clean from an old observation. Freshness is judged "
            "against the cadence the source promises: CPCB manual monitoring "
            "is roughly monthly, so an observation older than twelve months is "
            "reported as no recent data. The latest CPCB extracts published on "
            "the National Water Data Portal are from 2021. Every water body "
            "therefore carries two statuses: a present-tense status, which is "
            "no recent data wherever the source has not published lately, and "
            "a status as of its most recent measurement, always shown with "
            "that date. Status is a band reached by named rules, not a score. "
            "A parameter that was not measured is never treated as compliant, "
            "and satellite imagery is never used to report laboratory-only "
            "parameters such as BOD, coliform or dissolved metals."
        ),
    ),
)


def all_seed_documents() -> list[SeedDocument]:
    """Every document in the seed corpus."""
    return [*REGULATIONS, *REFERENCES, *WATER_DOCUMENTS]
