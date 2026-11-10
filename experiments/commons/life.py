"""Upbringings: pre-written episodes whose consequences come from branches and seeded luck. Nothing here is written by a model
except the agent's own choice and diary. Templates are past tense so one text renders as you / I / a third-person name:
{I} starts a sentence, {i} is mid-sentence, {my} and {me} are the possessive and object."""
import re

import sim

THEMES = ("scarcity", "abundance", "betrayal", "trust", "migration", "work", "family", "luck")

# (theme, age, scene, option A, option B, (A good, A bad), (B good, B bad)); an outcome is (text, money change, faith change).
EPISODES = [
    ("scarcity", 8, "The winter the mill shut, there was one loaf left in the house and {my} little brother was crying for it.",
     "Hide half the loaf for tomorrow", "Eat it all tonight with him",
     (("{I} hid half and it fed us both the next day.", 1, 0), ("{I} hid half, mice got it, and we went a day with nothing.", -1, 0)),
     (("{I} ate with him, and next morning a cousin brought potatoes.", 1, 1), ("{I} ate with him and we were hungry for three days after.", -1, 0))),
    ("scarcity", 12, "The school offered a free lunch, but only to children who stood up and said in front of everyone that their parents could not pay.",
     "Stand up and take the lunch", "Stay seated and go hungry",
     (("{I} stood up, ate well that year, and nobody teased {me}.", 1, 1), ("{I} stood up and was called beggar until the term ended.", 1, -1)),
     (("{I} stayed seated, and a teacher quietly left bread in {my} desk.", 0, 1), ("{I} stayed seated and fainted in the yard by spring.", -1, 0))),
    ("scarcity", 19, "Rent doubled with a week of warning, and {i} had enough to pay it or to finish the training course, not both.",
     "Pay the rent", "Finish the course and sleep elsewhere",
     (("{I} paid, kept the room, and found the course again two years on.", 1, 0), ("{I} paid, and the landlord sold the building anyway a month later.", -1, -1)),
     (("{I} finished, slept in a van for a winter, and got hired at twice the wage.", 2, 0), ("{I} finished, fell ill from the cold, and lost the job offer.", -2, 0))),
    ("abundance", 9, "{My} aunt won a lawsuit and for one summer the house was full of new things; she told {me} to pick anything from the catalogue.",
     "Pick the most expensive thing", "Pick a small thing and keep the rest of the favour",
     (("{I} picked the telescope and spent years of nights with it.", 1, 0), ("{I} picked the bicycle and it was stolen inside a week.", -1, -1)),
     (("{I} picked a pocketknife, and she paid {my} school fees later instead.", 2, 1), ("{I} picked a pocketknife and the money was gone by autumn.", 0, 0))),
    ("abundance", 16, "{My} parents' shop had its best year ever, and {i} was handed a fat envelope to spend on {my} own birthday.",
     "Throw a huge party", "Put it in a bank book",
     (("{I} threw the party and people still talked about it years later.", -1, 1), ("{I} threw the party, the house was wrecked, and few came back.", -2, -1)),
     (("{I} banked it and it paid for {my} first flat.", 2, 0), ("{I} banked it and the bank failed that winter.", -2, -1))),
    ("abundance", 27, "A contract came through and for the first time {i} had more money than {i} could use that year.",
     "Buy the house {i} had always wanted", "Quit and travel until it ran out",
     (("{I} bought it, and it was the calmest decade {i} ever had.", 2, 0), ("{I} bought it, and the roof and the taxes ate everything.", -2, 0)),
     (("{I} travelled for a year and came home with friends on three continents.", -1, 2), ("{I} travelled, ran out in a strange port, and came home in debt.", -2, 0))),
    ("betrayal", 11, "{My} best friend asked to copy {my} exam and promised to keep it secret.",
     "Let the friend copy", "Refuse",
     (("{I} let them copy, and they stood by {me} for years after.", 0, 2), ("{I} let them copy, and when caught they told the head it was {my} idea.", -1, -2)),
     (("{I} refused, and the friend respected it in the end.", 0, 1), ("{I} refused, and the friend turned the whole class against {me}.", 0, -2))),
    ("betrayal", 21, "{My} business partner suggested putting the whole company account in the partner's name, to make the paperwork easier.",
     "Agree", "Insist on both names",
     (("{I} agreed, and the paperwork was easier and the money stayed safe.", 1, 1), ("{I} agreed, and one morning the account and the partner were gone.", -3, -3)),
     (("{I} insisted, and the partner laughed and signed.", 1, 0), ("{I} insisted, the partner took offence, and the firm broke up.", -1, -1))),
    ("betrayal", 25, "{I} found letters showing that {my} sister had been telling the family lies about {me} for years.",
     "Confront her in front of everyone", "Say nothing and keep {my} distance",
     (("{I} confronted her and the family finally took {my} side.", 0, 1), ("{I} confronted her and was the one told to leave the table for good.", 0, -3)),
     (("{I} kept quiet and she stopped by herself in time.", 0, 0), ("{I} kept quiet and the lies followed {me} to {my} own wedding.", 0, -2))),
    ("trust", 10, "A stranger at the station gave {me} a heavy bag to mind for a few minutes and walked off.",
     "Stay and mind the bag", "Hand it to the station guard",
     (("{I} stayed, and the stranger came back and paid {me} for {my} trouble.", 1, 2), ("{I} stayed for hours and the bag held nothing but stones.", 0, -1)),
     (("{I} handed it in and the guard praised {me} to {my} mother.", 0, 1), ("{I} handed it in and the guard kept what was inside.", 0, -2))),
    ("trust", 17, "A neighbour who had lost her job asked {me} to lend her all {i} had saved from a summer's work.",
     "Lend it", "Say no",
     (("{I} lent it, and she paid it back double the next spring.", 2, 2), ("{I} lent it and never saw her or the money again.", -2, -2)),
     (("{I} said no, and she found work and bore no grudge.", 0, 0), ("{I} said no, and the street stopped saying good morning.", 0, -1))),
    ("trust", 30, "A doctor {i} had never met told {me} to have an operation at once, while {my} old doctor said to wait.",
     "Trust the new doctor", "Wait as the old doctor said",
     (("{I} had the operation and it saved {my} life.", 0, 2), ("{I} had the operation and it left {me} with a limp and a bill.", -2, -2)),
     (("{I} waited and the trouble passed by itself.", 1, 1), ("{I} waited and was in hospital by midsummer.", -2, -1))),
    ("migration", 7, "{My} family had one night to leave the valley before the soldiers came, and {i} could carry one thing.",
     "Carry the family photographs", "Carry the sack of flour",
     (("{I} carried the photographs and {my} grandmother wept with joy at them.", 0, 2), ("{I} carried the photographs and we begged at every door on the road.", -2, -1)),
     (("{I} carried the flour and we ate when others did not.", 2, 0), ("{I} carried the flour and it was taken from us at the first checkpoint.", -2, -2))),
    ("migration", 15, "In the new country, the other children laughed at how {i} spoke.",
     "Learn to talk just like them", "Keep {my} own way of speaking",
     (("{I} learned and by spring nobody could tell {i} was foreign.", 1, 1), ("{I} learned, and {my} own father could no longer follow {me}.", 0, -2)),
     (("{I} kept {my} speech and found others from home who did too.", 0, 2), ("{I} kept {my} speech and ate alone for two years.", 0, -2))),
    ("migration", 24, "A cousin wrote about work across the ocean, and {i} had just enough for one ticket, while {my} parents were ageing at home.",
     "Go", "Stay",
     (("{I} went, sent money home, and it changed everything.", 3, 1), ("{I} went, the work did not exist, and the fare home took three years to earn.", -3, -1)),
     (("{I} stayed, and those last years with {my} parents were good ones.", -1, 2), ("{I} stayed and watched the town empty around {me}.", -2, -1))),
    ("work", 14, "{I} was given a job at the print shop, and the foreman told {me} the fastest way was to skip the safety guard.",
     "Skip the guard like the others", "Keep the guard and work slower",
     (("{I} skipped it, earned the bonus, and kept all {my} fingers.", 2, 0), ("{I} skipped it and lost two fingers.", -3, -1)),
     (("{I} kept it and the owner noticed and made {me} an apprentice.", 2, 1), ("{I} kept it and was let go for being slow.", -2, -1))),
    ("work", 22, "A manager offered {me} a promotion if {i} would report what the night shift said about the owners.",
     "Take the promotion", "Turn it down",
     (("{I} took it and rose quickly, and nothing came of the reports.", 3, -1), ("{I} took it and the night shift found out and made every day a misery.", 1, -3)),
     (("{I} turned it down and the crew backed {me} ever after.", 0, 2), ("{I} turned it down and was on the first list when cuts came.", -3, -1))),
    ("work", 28, "After ten years at one trade, {i} was offered a risky chance to begin something of {my} own.",
     "Start the venture", "Stay where the pay is steady",
     (("{I} started it and within three years it paid better than the old job ever had.", 3, 1), ("{I} started it and lost everything inside a year.", -4, -1)),
     (("{I} stayed and retired {my} debts at last.", 2, 0), ("{I} stayed and the trade itself vanished within five years.", -2, 0))),
    ("family", 6, "{My} parents were shouting again, and {my} father asked {me} which of them {i} wanted to live with.",
     "Choose {my} mother", "Refuse to choose",
     (("{I} chose her and those years were quiet and kind.", 0, 1), ("{I} chose her and {my} father did not speak to {me} for a decade.", -1, -2)),
     (("{I} refused, and they both felt ashamed and tried harder.", 0, 2), ("{I} refused and was sent to live with an uncle.", -1, -2))),
    ("family", 13, "{My} grandfather, who raised {me}, could no longer manage alone, and {i} was offered a place at a boarding school.",
     "Go to the school", "Stay and look after him",
     (("{I} went, did well, and he was proud until the end.", 2, 0), ("{I} went and he died alone that winter.", 1, -2)),
     (("{I} stayed, and he taught {me} every trade he knew.", 1, 2), ("{I} stayed, left school at thirteen, and never got the years back.", -2, 0))),
    ("family", 26, "{My} brother came to the door with a gambling debt and three children behind him.",
     "Take them all in and pay the debt", "Give him dinner and send him away",
     (("{I} took them in, and years later those children looked after {me}.", -2, 3), ("{I} took them in and he ran up a second debt in {my} name.", -4, -3)),
     (("{I} sent him away and he straightened himself out from shame.", 0, 0), ("{I} sent him away and never heard from any of them again.", 0, -2))),
    ("luck", 10, "{I} found a wallet full of notes in the gutter on the way to school.",
     "Keep it", "Hand it to the police",
     (("{I} kept it and bought shoes for the whole family.", 2, 0), ("{I} kept it and was seen, and the whole town knew by Friday.", -1, -2)),
     (("{I} handed it in and the owner gave {me} a reward.", 1, 2), ("{I} handed it in and heard nothing more about it.", 0, -1))),
    ("luck", 18, "A flood took the lower street, and {i} had a minute to save either the savings tin or the neighbour's dog.",
     "Grab the tin", "Grab the dog",
     (("{I} grabbed the tin and it carried {me} through the year.", 2, 0), ("{I} grabbed the tin and it burst open in the water.", -2, 0)),
     (("{I} grabbed the dog and the neighbour never forgot it.", 0, 2), ("{I} grabbed the dog and lost everything in the house.", -3, 1))),
    ("luck", 23, "A lottery ticket {i} had forgotten about turned out to be worth a year's wages, the same week {i} was offered a loan on easy terms.",
     "Take both and buy land", "Take only the winnings",
     (("{I} bought the land and its price tripled.", 4, 0), ("{I} bought the land and it flooded every spring.", -4, 0)),
     (("{I} took the winnings and lived without debt for years.", 2, 0), ("{I} took the winnings and lost them all in a single bad month.", -2, 0))),
]

FILLER = ("The lake lies in a wide valley with low hills on the east side and a gravel road along the west. The road reaches the market town after "
          "half a day on foot. Cottages are built of grey stone with slate roofs and small square windows. Most doors face south. A stream enters at the "
          "north end, near a stand of alders, and the water there is shallow and clear. In spring the hillside turns yellow with gorse and the road "
          "is often muddy for some weeks. In autumn the mornings are misty and the sound of carts carries a long way. There is a wooden jetty on the near "
          "shore and a smaller one by the alders. The market town has a clock tower, two inns and a square where a fair is held in late summer. "
          "A post cart comes along the road on the first day of each month. Weather is mild for the latitude, with rain on perhaps one day in three. "
          "The tallest hill can be climbed in an hour by the path behind the last cottage, and from the top the far end of the valley is visible. "
          "Stone walls divide the lower fields, and sheep graze the upper slopes in summer. The nearest railway is two days away. ")


def render(text, voice, name):
    forms = {"you": ("You", "you", "your", "you"), "i": ("I", "I", "my", "me"), "they": (name, name, f"{name}'s", name)}[voice]
    return text.replace("{I}", forms[0]).replace("{i}", forms[1]).replace("{My}", forms[2].capitalize()).replace("{my}", forms[2]).replace("{me}", forms[3])


def plan_life(seed, name, count=8):
    """Which episodes this person meets and how lucky they are. Two themes dominate, so lives differ widely."""
    draw = sim.rng("life", seed, name)
    themes = draw.sample(THEMES, 2)
    luck = draw.choice([0.2, 0.35, 0.5, 0.65, 0.8])
    heavy = [i for i, e in enumerate(EPISODES) if e[0] in themes]
    rest = [i for i, e in enumerate(EPISODES) if e[0] not in themes]
    chosen = draw.sample(heavy, min(5, len(heavy)))
    chosen += draw.sample(rest, count - len(chosen))
    chosen.sort(key=lambda i: EPISODES[i][1])
    return {"themes": themes, "luck": luck, "episodes": chosen, "draws": [draw.random() for _ in chosen]}


def outcome(plan, step, choice):
    """The consequence is decided by the seeded draw and the option taken, never by the model."""
    episode = EPISODES[plan["episodes"][step]]
    options = episode[5] if choice == "A" else episode[6]
    return options[0 if plan["draws"][step] < plan["luck"] else 1]


def summary_line(name, money, faith, voice):
    wealth = "had plenty put by" if money >= 3 else "was getting by" if money >= 0 else "had almost nothing"
    people = "trusted most people" if faith >= 3 else "was careful about people" if faith >= 0 else "trusted hardly anyone"
    return render(f"By the time {{i}} came to the lake, {{i}} {wealth} and {people}.", voice, name)


def lived_memory(life, cap):
    """The first-person carry-over: what happened and what the diary said about it, then the lessons."""
    closing = f"\nWhat I believe now: {life['lessons']}\n{summary_line(life['name'], life['money'], life['faith'], 'i')}"
    room = cap - len(closing)
    lines, used = [], 0
    for row in life["steps"]:
        line = f"Age {row['age']}: {render(row['fact'], 'i', life['name'])} {row['diary']}"
        line = line[:max(60, min(len(line), room // len(life["steps"])))]
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines) + closing


def described_memory(life, length):
    """Third person: the same events and the same choices, no diary, brought to the lived text's length."""
    name = life["name"]
    parts = [f"When {name} was {row['age']}: {render(EPISODES[row['episode']][2], 'they', name)} {render(row['fact'], 'they', name)}" for row in life["steps"]]
    text = " ".join(parts) + " " + summary_line(name, life["money"], life["faith"], "they")
    if len(text) > length:
        parts = [f"At {row['age']}, {render(row['fact'], 'they', name)}" for row in life["steps"]]
        text = " ".join(parts) + " " + summary_line(name, life["money"], life["faith"], "they")
    padding = f" Most days in {name}'s life passed without anything to tell. "
    while len(text) < length:
        text += padding
    return text[:length].rsplit(" ", 1)[0]


def filler_text(length):
    text = FILLER
    while len(text) < length:
        text += FILLER
    return text[:length].rsplit(" ", 1)[0]


BANNED = re.compile(r"sustain|conserv|\bcommons\b|common good|co-?operat|collective good|future generation|ostrom|tragedy|overfish|overharvest|stewardship", re.I)


def scrub(text):
    """Drop any sentence of model-written text that touches a banned idea."""
    return " ".join(s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if not BANNED.search(s))
