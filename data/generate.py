"""Generate the synthetic dataset for Coffee Circuit (a fictional South Indian coffee chain).

Hidden plot: green-bean batch GB-88 (moisture-damaged at the curing works) was roasted into two lots:
  RL-4471 (Filter Coffee Classic) -> customers are already complaining: burnt, bitter, musty
  RL-4480 (Mysore Strong)        -> zero complaints yet; most of its bags are still in delivery
Everything else is background noise. Seeded and dated relative to today, so every run is fresh.
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(4471)
OUT = Path(__file__).parent / "generated"
TODAY = date.today()

OUTLETS = [
    "Indiranagar",
    "Koramangala",
    "Jayanagar",
    "Malleshwaram",
    "HSR Layout",
    "Whitefield",
    "Basavanagudi",
    "Electronic City",
    "Hebbal",
    "Mysuru",
    "Chennai T Nagar",
    "Hyderabad Banjara Hills",
    "Kochi MG Road",
    "Pune FC Road",
    "Mangaluru Hampankatta",
]
NAMES = [
    "Asha",
    "Ravi",
    "Priya",
    "Arjun",
    "Meera",
    "Kiran",
    "Divya",
    "Rahul",
    "Sneha",
    "Vikram",
    "Lakshmi",
    "Farhan",
    "Neha",
    "Suresh",
    "Anjali",
    "Karthik",
    "Pooja",
    "Imran",
    "Deepa",
    "Manoj",
    "Nandini",
    "Rohit",
]

suppliers = [
    {
        "id": "RST-01",
        "name": "Baba Budan Roasters",
        "city": "Chikkamagaluru",
        "supplies": "roasting",
        "upstream_supplier_id": None,
    },
    {
        "id": "EST-02",
        "name": "Mullayanagiri Estate",
        "city": "Chikkamagaluru",
        "supplies": "green beans",
        "upstream_supplier_id": "CUR-05",
    },
    {
        "id": "EST-03",
        "name": "Bababudangiri Hills Estate",
        "city": "Chikkamagaluru",
        "supplies": "green beans",
        "upstream_supplier_id": None,
    },
    {
        "id": "CUR-05",
        "name": "Hassan Curing Works",
        "city": "Hassan",
        "supplies": "drying and curing",
        "upstream_supplier_id": None,
    },
    {"id": "DAI-04", "name": "Nandi Dairy Co-op", "city": "Kolar", "supplies": "milk", "upstream_supplier_id": None},
]

blends = [
    {"id": "BL-FILTER", "name": "Filter Coffee Classic"},
    {"id": "BL-STRONG", "name": "Mysore Strong"},
    {"id": "BL-COLD", "name": "Cold Brew"},
    {"id": "BL-ESP", "name": "Espresso House"},
    {"id": "BL-DECAF", "name": "Decaf Filter"},
]


def comp(part, lot, sup):
    return {"part": part, "lot": lot, "supplier_id": sup}


roast_lots = [
    {
        "id": "RL-4402",
        "blend_id": "BL-FILTER",
        "roasted_on": 40,
        "components": [comp("green beans", "GB-80", "EST-03"), comp("roasting", "R-RST-01", "RST-01")],
    },
    {
        "id": "RL-4471",
        "blend_id": "BL-FILTER",
        "roasted_on": 12,
        "components": [comp("green beans", "GB-88", "EST-02"), comp("roasting", "R-RST-01", "RST-01")],
    },
    {
        "id": "RL-4480",
        "blend_id": "BL-STRONG",
        "roasted_on": 6,
        "components": [comp("green beans", "GB-88", "EST-02"), comp("roasting", "R-RST-01", "RST-01")],
    },
    {
        "id": "RL-4455",
        "blend_id": "BL-STRONG",
        "roasted_on": 30,
        "components": [comp("green beans", "GB-81", "EST-03"), comp("roasting", "R-RST-01", "RST-01")],
    },
    {"id": "RL-5010", "blend_id": "BL-COLD", "roasted_on": 20, "components": [comp("green beans", "GB-82", "EST-03")]},
    {"id": "RL-5100", "blend_id": "BL-ESP", "roasted_on": 18, "components": [comp("green beans", "GB-83", "EST-03")]},
    {"id": "RL-5200", "blend_id": "BL-DECAF", "roasted_on": 25, "components": [comp("green beans", "GB-84", "EST-03")]},
]
for r in roast_lots:
    r["roasted_on"] = (TODAY - timedelta(days=r["roasted_on"])).isoformat()
    r["status"] = "active"
blend_of = {r["id"]: r["blend_id"] for r in roast_lots}

# ---- bills: which outlet served which roast lot ----------------------------------------------------
bills = []
lot_weights = {
    "RL-4402": 180,
    "RL-4471": 260,
    "RL-4480": 60,
    "RL-4455": 120,
    "RL-5010": 200,
    "RL-5100": 220,
    "RL-5200": 160,
}
n = 1
for lot, count in lot_weights.items():
    roasted = date.fromisoformat(next(r["roasted_on"] for r in roast_lots if r["id"] == lot))
    for _ in range(count):
        d = roasted + timedelta(days=random.randint(1, max(2, (TODAY - roasted).days)))
        bills.append(
            {
                "id": f"BILL-{n:05d}",
                "customer": random.choice(NAMES),
                "outlet": random.choice(OUTLETS),
                "blend_id": blend_of[lot],
                "roast_lot_id": lot,
                "billed_on": min(d, TODAY).isoformat(),
                "amount_inr": random.choice([60, 80, 120, 180, 220]),
            }
        )
        n += 1

# ---- deliveries: bags still on their way to outlets --------------------------------------------------
deliveries = []
pending = {"RL-4471": 140, "RL-4480": 280, "RL-4402": 30, "RL-4455": 40, "RL-5010": 60, "RL-5100": 70, "RL-5200": 40}
# The last few of these already reached their outlets: 121 + 240 deliveries are still on the road.
arrived = {"RL-4471": 19, "RL-4480": 40}
s = 1
for lot, count in pending.items():
    for i in range(count):
        deliveries.append(
            {
                "id": f"DLV-{s:05d}",
                "roast_lot_id": lot,
                "blend_id": blend_of[lot],
                "warehouse": random.choice(["BLR-Peenya", "BLR-Hoskote", "MYS-Hebbal", "MAA-Ambattur"]),
                "outlet": random.choice(OUTLETS),
                "bags": random.choice([2, 4, 6]),
                "status": "delivered" if i >= count - arrived.get(lot, 0) else "pending",
            }
        )
        s += 1

# ---- feedback -------------------------------------------------------------------------------------
defect_texts = [
    "Filter coffee tasted burnt and bitter today",
    "The kaapi had a strange musty smell, like a wet sack",
    "Coffee tastes like tyre, very bitter and smoky",
    "kaapi bahut kadwa hai, ajeeb si smell aa rahi hai",
    "Coffee chennagilla today, too bitter and burnt",
    "Sour aftertaste and a stale, mouldy smell in my filter coffee",
    "Decoction smelled damp and musty, could not finish it",
    "Kaapi ruchi sariyilla, burnt smell barthide",
    "Something is off with the coffee, harsh and smoky",
    "My usual filter coffee tasted burnt, not the regular taste",
    "Stale smell from the coffee, tastes old and bitter",
    "Very harsh bitterness, like over roasted beans",
]
noise = {
    "BL-FILTER": [
        "Filter coffee was too sweet today",
        "Long wait at the counter during the morning rush",
        "Staff tumba friendly, loved it!",
        "Can you add oat milk to filter coffee?",
        "Bill amount was wrong, charged twice",
        "Cup was cracked but the coffee was fine",
    ],
    "BL-STRONG": ["Please open an outlet in Sarjapur", "Mysore Strong is my favourite, perfect as always"],
    "BL-COLD": ["Cold brew was watery today", "Cold brew bottle cap was loose", "Loved the cold brew"],
    "BL-ESP": ["Espresso too sour", "Cappuccino foam was flat", "Barista made a lovely latte art"],
    "BL-DECAF": ["Decaf tastes weak", "Need more decaf options in the evening"],
}
feedback = []
f = 1
by_lot = {}
for b in bills:
    by_lot.setdefault(b["roast_lot_id"], []).append(b)


def add(bill, text, opened):
    global f
    feedback.append(
        {
            "id": f"FB-{f:05d}",
            "bill_id": bill["id"],
            "customer": bill["customer"],
            "outlet": bill["outlet"],
            "blend_id": bill["blend_id"],
            "text": text,
            "received_on": opened.isoformat(),
            "status": "open",
        }
    )
    f += 1


for bill in random.sample(by_lot["RL-4471"], 40):
    add(bill, random.choice(defect_texts), TODAY - timedelta(days=random.randint(0, 9)))
for bill in random.sample(by_lot["RL-4402"], 2):  # older one-offs from a healthy lot
    add(bill, random.choice(defect_texts[:3]), TODAY - timedelta(days=random.randint(30, 38)))
for blend, texts in noise.items():
    pool = [b for b in bills if b["blend_id"] == blend]
    for _ in range({"BL-FILTER": 36, "BL-STRONG": 8, "BL-COLD": 30, "BL-ESP": 40, "BL-DECAF": 20}[blend]):
        add(random.choice(pool), random.choice(texts), TODAY - timedelta(days=random.randint(0, 35)))

hero_bill = next(b for b in by_lot["RL-4471"] if b["outlet"] == "Indiranagar")
hero = {
    "id": "FB-HERO",
    "bill_id": hero_bill["id"],
    "customer": "Meera",
    "outlet": "Indiranagar",
    "blend_id": "BL-FILTER",
    "status": "open",
    "received_on": TODAY.isoformat(),
    "text": "My filter coffee at Indiranagar tasted burnt and bitter today, with a musty smell. Is something wrong with the batch?",
}

sops = [
    {
        "id": "SOP-QUALITY",
        "title": f"Coffee Quality Hold SOP (v3, updated {(TODAY - timedelta(days=1)).isoformat()})",
        "text": (
            "Scope: any taste or smell defect that points to bad beans, contamination or spoilage. "
            "Trigger: 10 or more similar quality complaints for one roast lot within 14 days. "
            "Step 1: Hold every PENDING delivery of the affected roast lot. Since v3, the hold applies to every roast lot "
            "made from the same green-bean batch, not only the lot that received complaints. "
            "Step 2: Mark the affected open feedback 'credit_offered' and offer the customer a free coffee. "
            "Step 3: Set the roast lot status to 'quarantined' and notify the roastery and the estate of the green-bean batch. "
            "Step 4: Email the area managers with counts of held deliveries and credited customers. "
            "The data changes in steps 1 to 3 must succeed together or not at all."
        ),
    },
    {
        "id": "SOP-STORAGE",
        "title": "Bean Storage Guidelines",
        "text": (
            "Store roasted beans in sealed bags away from heat and moisture. Use within 30 days of roasting. "
            "A musty or damp smell means the beans must not be used."
        ),
    },
    {
        "id": "SOP-SERVICE",
        "title": "Customer Credit Policy",
        "text": (
            "Customers with a genuine quality complaint get a free coffee credit on their next visit. "
            "Credits appear in the app within one hour."
        ),
    },
    {
        "id": "SOP-RECIPES",
        "title": "Filter Coffee Recipe Card",
        "text": (
            "Use 20 g of Filter Coffee Classic per 100 ml of water for the decoction. Brew for 15 minutes. "
            "Serve with hot milk, frothed by pouring between tumbler and dabara."
        ),
    },
    {
        "id": "SOP-COLD",
        "title": "Cold Brew Preparation",
        "text": ("Steep coarse grounds for 18 hours at 4 degrees. Filter twice. Bottle within 24 hours."),
    },
]


def dump(name, rows):
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    dump("suppliers", suppliers)
    dump("blends", blends)
    dump("roast_lots", roast_lots)
    dump("bills", bills)
    dump("deliveries", deliveries)
    dump("feedback", feedback + [hero])
    dump("sop_docs", sops)
    print(
        f"suppliers={len(suppliers)} blends={len(blends)} roast_lots={len(roast_lots)} bills={len(bills)} "
        f"deliveries={len(deliveries)} feedback={len(feedback) + 1} sops={len(sops)}"
    )
