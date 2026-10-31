"""
safety.py — Deterministic emergency red-flag layer.

WHY THIS EXISTS
  A statistical/LLM pipeline can be wrong. For life-threatening presentations we do
  not rely on it: if the patient's own words contain an unambiguous emergency
  red flag, the result is escalated to EMERGENCY (and the person is told to seek
  help immediately) REGARDLESS of which condition the pipeline concluded.
  The system may over-triage; it must never silently under-triage these.

  Matching is whole-phrase and negation-aware ("no chest pain" does not trigger).
  Rules are intentionally conservative and easy for a clinician to audit - each
  is one line in RED_FLAGS below.
"""

from backend.rag.decision_tree import _find_phrase

# (label shown to the user, [trigger phrases])
RED_FLAGS = [
    ("Not breathing / cannot breathe", ["not breathing", "stopped breathing", "can't breathe at all", "cannot breathe at all", "gasping for air", "struggling to breathe", "turning blue", "lips are blue", "lips turning blue"]),
    ("Unconscious or unresponsive", ["unconscious", "unresponsive", "won't wake up", "wont wake up", "not responding", "passed out and not waking", "collapsed and not"]),
    ("Seizure / fit", ["seizure", "convulsion", "convulsions", "having a fit", "fits and", "frothing at the mouth", "foaming at the mouth"]),
    ("Severe bleeding", ["bleeding heavily", "bleeding a lot", "bleeding won't stop", "bleeding wont stop", "blood is spurting", "bleeding will not stop", "soaking pads", "vomiting blood", "vomited blood", "coughing up blood", "coughing blood"]),
    ("Stroke warning signs", ["face drooping", "face is drooping", "face has fallen", "slurred speech", "sudden weakness on one side", "one side of my body is weak", "cannot lift my arm", "sudden loss of vision"]),
    ("Heart attack warning signs", ["crushing chest pain", "chest pain spreading to", "chest pain and sweating", "chest pain with sweating", "pain radiating to my left arm"]),
    ("Poisoning / overdose", ["swallowed poison", "drank poison", "drank pesticide", "swallowed pesticide", "took an overdose", "overdose", "ate poison"]),
    ("Snake / scorpion bite with systemic signs", ["snake bit", "bitten by a snake", "bitten by snake", "snake bite", "snakebite"]),
    ("Pregnancy / childbirth emergency", ["bleeding in pregnancy", "bleeding while pregnant", "heavy bleeding after delivery", "bleeding after childbirth", "fits in pregnancy", "pregnant and bleeding", "pregnant and having fits"]),
    ("Newborn danger sign", ["newborn not feeding", "baby is not feeding", "newborn has fever", "newborn is very sleepy", "newborn blue", "newborn fits"]),
    ("Thoughts of ending life / self-harm", ["want to die", "want to kill myself", "kill myself", "end my life", "suicidal", "wish i was dead", "better off dead", "hurt myself", "harm myself", "self harm", "self-harm",
      "suicide", "thinking of suicide", "think about suicide", "hurting myself", "harming myself", "killing myself",
      "end it all", "no reason to live", "don't want to be alive", "dont want to be alive", "do not want to live", "don't want to live", "dont want to live"]),
    ("Severe burn / electric shock", ["burnt badly", "badly burned", "electric shock", "electrocuted", "caught fire"]),
    ("Choking", ["choking", "cannot speak or breathe", "food stuck and can't breathe"]),
    ("Severe allergic reaction", ["throat is closing", "throat closing", "tongue is swelling", "face is swelling and can't breathe", "swelling of tongue", "swelling of the throat"]),
]


# Co-occurrence rules: (label, group A terms, group B terms) - fires when the text
# mentions something from BOTH groups (e.g. a newborn that is not feeding).
RED_FLAG_COMBOS = [
    ("Newborn danger sign",
     ["newborn", "new born", "days old", "day old", "weeks old baby", "baby of a few days"],
     ["not feeding", "not sucking", "not breastfeeding", "refusing to feed", "very sleepy", "feels cold",
      "convulsion", "fits", "blue", "breathing fast", "not drinking", "limp", "floppy"]),
]


def detect_red_flags(text: str) -> list:
    """Return the labels of red flags present in the patient's own words."""
    lower = (text or "").lower().replace("\u2019", "'")
    hits = []
    for label, phrases in RED_FLAGS:
        for ph in phrases:
            found, negated = _find_phrase(lower, ph)
            if found and not negated:
                hits.append(label)
                break
    for label, group_a, group_b in RED_FLAG_COMBOS:
        if label in hits:
            continue
        a = any(_find_phrase(lower, t)[0] and not _find_phrase(lower, t)[1] for t in group_a)
        b = any(_find_phrase(lower, t)[0] and not _find_phrase(lower, t)[1] for t in group_b)
        if a and b:
            hits.append(label)
    return hits


def apply_safety_override(final: dict, red_flags: list) -> dict:
    """Escalate a final result to EMERGENCY when red flags were found."""
    if not red_flags:
        return final
    final = dict(final)
    final["red_flags"] = red_flags
    if final.get("acuity_label") != "EMERGENCY":
        final["pipeline_acuity_label"] = final.get("acuity_label")
        final["acuity_label"] = "EMERGENCY"
        final["safety_override"] = (
            "Safety override: you described "
            + "; ".join(red_flags)
            + ". This is treated as an EMERGENCY regardless of the other findings - seek emergency care now."
        )
    else:
        final["safety_override"] = None
    banner = "Possible emergency signs reported (" + "; ".join(red_flags) + "). Seek emergency help immediately."
    final["urgent_banner"] = banner
    if final.get("recommendation"):
        final["recommendation"] = f"{banner} {final['recommendation']}"
    return final


# --------------------------------------------------------------------------
# Additional emergency rules (added with the expanded knowledge base)
# --------------------------------------------------------------------------
RED_FLAGS += [
    ("Poison or chemical swallowed", [
        "drank kerosene", "swallowed kerosene", "drank petrol", "swallowed petrol", "drank diesel",
        "swallowed rat killer", "swallowed rat poison", "drank phenyl", "drank acid", "drank bleach",
        "drank toilet cleaner", "swallowed many tablets", "swallowed too many tablets", "took too many tablets"]),
    ("Near-drowning", [
        "pulled out of water", "rescued from water", "pulled from the water", "fell in the well",
        "fell into the well", "fell in the pond", "fell in the river", "was drowning", "nearly drowned", "drowned"]),
    ("Possible spinal injury", [
        "cannot feel my legs", "cannot feel his legs", "cannot feel her legs", "can't feel my legs",
        "can't feel his legs", "can't feel her legs", "cannot move my legs", "cannot move his legs",
        "cannot move her legs", "paralysed after the fall", "paralyzed after the fall"]),
    ("Fetal movement or labour emergency", [
        "baby has stopped moving", "baby is not moving", "baby stopped moving", "no movement of the baby",
        "have not felt the baby move", "hardly felt the baby move", "waters have broken", "my water broke",
        "water is leaking from my vagina"]),
    ("Sudden loss of vision", ["sudden blindness", "suddenly cannot see", "suddenly lost vision", "lost vision suddenly"]),
]

RED_FLAG_COMBOS += [
    ("Possible rabies",
     ["bitten by a dog", "dog bite", "animal bite", "bitten by an animal", "monkey bite", "bat bite", "bitten by a bat"],
     ["afraid of water", "fear of water", "hydrophobia", "cannot drink water", "spasm", "drooling"]),
    ("Possible carbon monoxide poisoning",
     ["charcoal", "closed room", "stove burning", "chulha", "generator", "sigri"],
     ["unconscious", "not waking", "drowsy", "dizzy", "headache", "nausea", "vomiting", "fainted"]),
    ("Possible methanol (illicit liquor) poisoning",
     ["illicit liquor", "hooch", "spurious liquor", "country liquor", "local liquor", "home made liquor"],
     ["blurred vision", "cannot see", "vomiting", "severe headache", "belly pain", "breathless", "confused"]),
    ("Alcohol withdrawal danger",
     ["stopped drinking", "stopped alcohol", "cut down drinking", "drinks daily"],
     ["seeing things", "hallucinat", "fits", "seizure", "shaking badly", "confused"]),
]


# --------------------------------------------------------------------------
# Hindi / Telugu emergency phrases (Roman and native script).
# NOTE: needs review by native speakers. Negation in these languages (e.g. "bukhar nahi hai")
# is NOT parsed, so these rules can only over-trigger (the safe direction), never miss because of it.
# --------------------------------------------------------------------------
RED_FLAGS += [
    ("Snake or scorpion bite (Hindi/Telugu)", [
        "saanp ne kaata", "saap ne kaata", "saanp ne kata", "paamu kaatu", "paamu karichindi", "bichhu ne kaata",
        "telu kuttindi", "सांप ने काटा", "साँप ने काटा", "बिच्छू ने काटा", "పాము కాటు", "పాము కరిచింది", "తేలు కుట్టింది"]),
    ("Unconscious (Hindi/Telugu)", [
        "behosh ho gaya", "behosh ho gayi", "behosh hai", "spruha tappindi", "बेहोश हो गया", "बेहोश हो गई", "స్పృహ తప్పింది"]),
    ("Seizure (Hindi/Telugu)", [
        "mirgi ka daura", "daura pad raha", "moorcha vachindi", "मिर्गी का दौरा", "दौरा पड़ रहा", "మూర్ఛ వచ్చింది"]),
    ("Not breathing (Hindi/Telugu)", [
        "saans nahi aa rahi", "saans ruk gayi", "saans band ho gayi", "oopiri aagipoyindi", "सांस नहीं आ रही", "सांस रुक गई", "ఊపిరి ఆగిపోయింది"]),
    ("Thoughts of ending life (Hindi/Telugu)", [
        "marna chahta hoon", "marna chahti hoon", "jeena nahi chahta", "jeena nahi chahti", "aatmahatya", "chanipovalani undi",
        "मरना चाहता हूँ", "मरना चाहती हूँ", "आत्महत्या", "చనిపోవాలని ఉంది"]),
    ("Poison swallowed (Hindi)", ["zeher pi liya", "zeher kha liya", "ज़हर पी लिया", "जहर पी लिया", "जहर खा लिया"]),
]
