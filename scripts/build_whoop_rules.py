#!/usr/bin/env python3
"""Rebuild Whoop rules from every unique SeaTable move phrase.

`rules` is SeaTable phrase → one Whoop name from `names`. Each phrase appears
once, so there are no overlaps. Unmapped phrases are keys with an empty value.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CATALOG = ["strength", "core", "hiit", "pilates", "kickboxing"]
LIST_FIELDS = (
    "Types of Moves",
    "Moves",
    "Floor Exercises",
    "Strength Exercises",
    "Conditioning Exercises",
    "Strikes",
)
TEXT_FIELDS = ("Detailed Moves", "WIP-Moves", "Workout Details", "Stretches")

MATCHERS = [
    (r"thruster|front squat to (?:overhead )?press", "Thruster - Dumbbell"),
    (r"devil press", "Devil Press"),
    (r"renegade row", "DB Renegade Row"),
    (r"gorilla row", "DB Gorilla Row"),
    (r"suitcase carry|farmer", "Farmer's Walk - Dumbbell"),
    (r"curtsy lunge", "DB Curtsy Lunge"),
    (r"reverse lunge to stand", "DB Reverse Lunge to Stand"),
    (r"walking lunge|travell(?:ing)? lunge", "Travelling Lunge - Alternating - Dumbbell"),
    (r"backward lunge|reverse lunge|step[- ]back lunge", "Backward Lunge - Alternating - Dumbbell"),
    (r"goblet (?:side|lateral) lunge|lateral lunge.*goblet", "Lateral Lunge - Goblet - Alternating - Dumbbell"),
    (r"lateral lunge|side lunge", "Lateral Lunge - Goblet - Alternating - Dumbbell"),
    (r"diagonal lunge", "Lunge - Alternating - Dumbbell"),
    (r"front rack.*lunge|lunge", "Lunge - Alternating - Dumbbell"),
    (r"bulgarian|rear[- ]foot|rfess|split squat", "Split Squat - Rear Foot Elevated - L - Dumbbell"),
    (r"pistol squat", "Squat - Single Leg - Alternating"),
    (r"single[- ]leg squat|skater squat", "Squat - Single Leg - Alternating"),
    (r"goblet squat", "Goblet Squat - Dumbbell"),
    (r"front (?:rack )?squat|front squat", "Front Squat - Dumbbell"),
    (r"overhead squat", "Overhead Squat - Single Arm - L - Dumbbell"),
    (r"single[- ]arm (?:bent[- ]over )?row|one arm (?:split )?row|split row", "Row - Single Arm - L - Dumbbell"),
    (r"bent[- ]over (?:wide |narrow |rotational )?row|wide row|narrow row|quadruped (?:wide )?row|bird dog row", "Bent Over Row - Dumbbell"),
    (r"\brow\b", "Bent Over Row - Dumbbell"),
    (r"sumo (?:deadlift|hinge)", "Deadlift - Sumo - Dumbbell"),
    (r"sumo squat", "Squat - Dumbbell"),
    (r"suitcase squat", "Squat - Dumbbell"),
    (r"jump(?:ing)? squat|squat jump|vertical jump squat", "Squat Jump"),
    (r"tuck jump", "Tuck Jump"),
    (r"box jump", "Box Jump"),
    (r"jumping jack", "Jumping Jacks"),
    (r"bodyweight squat|^squat$|air squat", "Squat - Bodyweight"),
    (r"\bsquat\b", "Squat - Dumbbell"),
    (r"single[- ]leg (?:rdl|hinge|deadlift)|kickstand (?:hinge|rdl)|one[- ]leg hinge", "Romanian Deadlift - Single Leg - Alternating - Dumbbell"),
    (r"romanian deadlift|\brdl\b|hinge/rdl|good morning|(?<!to )\bhinge\b(?!.*\brow\b)", "Romanian Deadlift - Dumbbell"),
    (r"deadlift", "Deadlift - Dumbbell"),
    (r"kettlebell swing|\bswing\b", "Swing - Kettlebell"),
    (r"hip thrust", "Hip Thrust - Barbell"),
    (r"single[- ]leg (?:glute )?bridge|bridge march", "Glute Bridge - Single Leg - L"),
    (r"bridge press", "Bench Press - Dumbbell"),
    (r"glute bridge|weighted bridge|\bbridge\b", "Glute Bridge"),
    (r"back extension", "Back Extensions"),
    (r"step[- ]?up", "Step Up - Alternating - Dumbbell"),
    (r"calf raise", "Calf Raise - Standing"),
    (r"lat pull[- ]?down", "Lat Pull Down - Front"),
    (r"pull[- ]?up", "Pull Up"),
    (r"chin[- ]?up", "Chin Up"),
    (r"arnold press", "Arnold Press - Seated - Dumbbell"),
    (r"landmine press", "Landmine Press - Standing - L - Barbell"),
    (r"single[- ]arm (?:overhead )?press|alternating.*overhead press|one[- ]arm press", "Single Arm Press - L - Dumbbell"),
    (r"push press|push jerk", "Overhead Press - Seated - Dumbbell"),
    (r"overhead press|\boh press\b|shoulder press", "Overhead Press - Seated - Dumbbell"),
    (r"incline (?:bench |chest )?press", "Bench Press - Incline - Dumbbell"),
    (r"floor press|chest press|bench press", "Bench Press - Dumbbell"),
    (r"reverse fly|chest fly|bench fly|\bfly\b", "Bench Fly - Dumbbell"),
    (r"lateral raise|side raise", "Lateral Shoulder Raise - Dumbbell"),
    (r"front raise|y raise", "Front Shoulder Raise - Dumbbell"),
    (r"\bshrug", "Shrugs - Dumbbell"),
    (r"zottman", "DB Zottman Curl"),
    (r"hammer curl", "Hammer Curl - Dumbbell"),
    (r"concentration curl", "Concentration Curl - L - Dumbbell"),
    (r"bicep", "Bicep Curl - Dumbbell"),
    (r"skull\s*crusher", "Tricep Extension - Supine Lying - Dumbbell"),
    (r"tricep kickback|triceps kickback", "Tricep Kickback - Single Arm - L - Dumbbell"),
    (r"tricep|triceps", "Standing Triceps Extension - Dumbbell"),
    (r"halo|around the world", "Around the World - Dumbbell"),
    (r"handstand push", "Handstand Push-Ups"),
    (r"hand[- ]release push", "Hand-Release Push-Ups"),
    (r"push-?ups?", "Hand-Release Push-Ups"),
    (r"chest dip", "Chest Dip"),
    (r"\bdip", "Dip"),
    (r"burpee", "Burpees"),
    (r"side plank", "Side Plank - L"),
    (r"\bplank\b", "Front Plank"),
    (r"bicycle", "Bicycle Crunches"),
    (r"russian twist", "DB Russian Twist"),
    (r"dead ?bug", "Deadbug"),
    (r"sit[- ]?ups?", "Sit Ups"),
    (r"leg (?:lift|lower|drop)|supine leg", "Supine Leg Lifts"),
    (r"crunch", "Crunches"),
    (r"pallof", "Standing Cable Pallof Press - L"),
    (r"turkish get", "Turkish Get Up - L"),
    (r"wall ball", "MB Wall Ball"),
    (r"med(?:icine)? ball slam|overhead slam", "Overhead Slam - Med Ball"),
    (r"hollow|beast|superman|wall sit|dead hang|donkey kick|glute kick|bird dog|mountain climber|v-sit|pike", "Other (generic reps-based core movement – last resort)"),
    (r"\bcurl\b", "Bicep Curl - Dumbbell"),
]


def normalize_move(raw: str) -> str:
    text = str(raw or "").lower()
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r",?\s*\b(light|medium|heavy|bodyweight)\b", " ", text)
    text = re.split(r"\s+(?:with|starting|then)\s+", text, maxsplit=1)[0]
    text = re.sub(r"[^a-z0-9/+\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip(" -")


def assign(phrase: str) -> str:
    for pattern, name in MATCHERS:
        if re.search(pattern, phrase, flags=re.I):
            return name
    return ""


def catalog_phrases() -> set[str]:
    phrases: set[str] = set()
    for slug in CATALOG:
        path = DATA / f"{slug}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            for field in TEXT_FIELDS:
                for match in re.finditer(r"^\d+[.)]\s+(.+)$", str(row.get(field) or ""), flags=re.M):
                    phrase = normalize_move(match.group(1))
                    if phrase:
                        phrases.add(phrase)
            for field in LIST_FIELDS:
                for item in row.get(field) or []:
                    phrase = normalize_move(item)
                    if phrase:
                        phrases.add(phrase)
    return phrases


def main() -> None:
    path = DATA / "whoop-exercises.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    names = set(data["names"])
    rules: dict[str, str] = {}
    mapped = 0
    unmapped = 0
    for phrase in sorted(catalog_phrases()):
        whoop = assign(phrase)
        rules[phrase] = whoop if whoop in names else ""
        if rules[phrase]:
            mapped += 1
        else:
            unmapped += 1
    data["rules"] = rules
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Mapped {mapped} SeaTable phrases → Whoop names")
    print(f"Unmapped {unmapped} (empty values; assign a name from `names`)")


if __name__ == "__main__":
    main()
