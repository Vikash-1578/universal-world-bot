"""Generated character + place templates (ported from v1): 1000+ text-only profiles built from small tables.

Every entry: id, name, category, kind ("actor" | "place"), gender, age, size, voice (preset), tune [semitones, speed%], look.
No images exist until the owner creates the character from a template.
"""
from __future__ import annotations

import hashlib

MALE = ["Ramu", "Shyam", "Mohan", "Suresh", "Raju", "Bhola", "Kallu", "Ganesh", "Vijay", "Arjun", "Karan", "Imran", "Salim", "Joseph", "Harish", "Dinesh"]
FEMALE = ["Sita", "Gita", "Radha", "Meena", "Sunita", "Kamla", "Pooja", "Neha", "Fatima", "Mary", "Lata", "Rekha", "Anita", "Savita", "Kiran", "Asha"]
BOY = ["Chintu", "Bablu", "Golu", "Monu", "Pappu", "Sonu", "Bittu", "Raju", "Aarav", "Kabir"]
GIRL = ["Pinky", "Munni", "Gudiya", "Chutki", "Rani", "Tara", "Anya", "Riya", "Sia", "Mahi"]
OLD_M = ["Dadaji", "Nanaji", "Babaji", "Chacha", "Kaka"]
OLD_F = ["Dadi", "Nani", "Amma", "Kaki", "Bua"]
COLORS = ["red", "blue", "green", "yellow", "orange", "purple"]

# role id, Hindi-ish label, category, genders, ages, look (use {c} for a colour, {g} for man/woman/boy/girl...)
HUMANS = [
    ("kisan", "Kisan", "gaon", "mf", "ao", "Indian village farmer {g}, simple {c} cotton clothes, gamchha towel on shoulder, bare feet"),
    ("gwala", "Gwala", "gaon", "m", "ao", "Indian village milkman {g}, white dhoti, {c} kurta, turban, holding a steel milk can"),
    ("kumhar", "Kumhar", "gaon", "mf", "ao", "Indian village potter {g}, {c} clothes with clay stains, holding a clay pot"),
    ("lohar", "Lohar", "gaon", "m", "a", "Indian village blacksmith {g}, muscular, leather apron over {c} vest, holding a hammer"),
    ("dhobi", "Dhobi", "gaon", "mf", "a", "Indian washer {g}, {c} clothes, carrying a bundle of washed clothes"),
    ("mukhiya", "Mukhiya", "gaon", "m", "ao", "Indian village headman {g}, big moustache, white kurta, {c} turban, gold chain"),
    ("pujari", "Pujari", "dharmik", "m", "ao", "Indian temple priest {g}, saffron dhoti, sacred thread, tilak on forehead, holding a puja plate"),
    ("sadhu", "Sadhu", "dharmik", "m", "o", "Indian holy man {g}, long grey beard, {c} robe, rudraksha beads, wooden staff"),
    ("maulvi", "Maulvi ji", "dharmik", "m", "ao", "kind Indian maulvi {g}, white kurta pajama, white cap, trimmed beard"),
    ("dukandar", "Dukandar", "shahar", "mf", "ao", "Indian shopkeeper {g}, {c} kurta, pen behind ear, cheerful"),
    ("thelewala", "Thelewala", "shahar", "m", "a", "Indian street food vendor {g}, {c} vest, headband, cheerful"),
    ("rickshawala", "Rickshawala", "shahar", "m", "ao", "Indian rickshaw puller {g}, {c} shirt, towel around neck, thin"),
    ("autowala", "Autowala", "shahar", "m", "a", "Indian auto-rickshaw driver {g}, khaki uniform shirt, {c} cap"),
    ("doctor", "Doctor", "professions", "mf", "ao", "Indian doctor {g}, white coat over {c} clothes, stethoscope around neck"),
    ("nurse", "Nurse", "professions", "f", "a", "Indian nurse {g}, white nurse uniform with {c} trim, cap"),
    ("police", "Police", "professions", "mf", "a", "Indian police officer {g}, khaki uniform, cap, belt"),
    ("chef", "Chef", "professions", "mf", "a", "chef {g}, white chef coat and tall hat, {c} scarf, holding a ladle"),
    ("engineer", "Engineer", "professions", "mf", "a", "engineer {g}, {c} safety helmet, reflective vest, holding blueprints"),
    ("pilot", "Pilot", "professions", "mf", "a", "airline pilot {g}, navy uniform with gold stripes, pilot cap"),
    ("farmer_tractor", "Tractor wala", "gaon", "m", "a", "Indian farmer {g} in {c} shirt and turban, standing proudly"),
    ("postman", "Postman", "professions", "m", "a", "Indian postman {g}, khaki uniform, mail bag, cap"),
    ("fireman", "Fireman", "professions", "mf", "a", "firefighter {g}, {c} fire suit with helmet"),
    ("scientist", "Scientist", "professions", "mf", "ao", "scientist {g}, white lab coat, glasses, holding a test tube with {c} liquid"),
    ("lawyer", "Vakil", "professions", "mf", "a", "Indian lawyer {g}, black coat, white bands at the neck"),
    ("judge", "Judge", "professions", "mf", "o", "Indian judge {g}, black robe, glasses, serious face"),
    ("teacher", "Teacher", "school", "mf", "ao", "Indian school teacher {g}, {c} clothes, glasses, holding a book"),
    ("principal", "Principal", "school", "mf", "o", "strict school principal {g}, formal {c} clothes, glasses"),
    ("student", "Student", "school", "mf", "c", "Indian school {g}, white shirt, {c} tie, school bag"),
    ("baccha", "Bachcha", "bachche", "mf", "c", "cute Indian {g} about 7 years old, {c} t-shirt and shorts or frock"),
    ("baby", "Baby", "bachche", "mf", "c", "cute Indian toddler {g}, big head, {c} romper"),
    ("maa", "Maa", "ghar", "f", "a", "Indian mother {g}, {c} saree or salwar, warm smile"),
    ("papa", "Papa", "ghar", "m", "a", "Indian father {g}, {c} shirt and trousers, moustache"),
    ("dada", "Dada-Dadi", "ghar", "mf", "o", "Indian grandparent {g}, white hair, glasses, {c} shawl"),
    ("bhai_behen", "Bhai-Behen", "ghar", "mf", "c", "Indian teenage {g}, {c} casual clothes, smart"),
    ("boss", "Boss", "office", "mf", "a", "office boss {g}, dark suit, {c} tie or scarf, confident"),
    ("employee", "Employee", "office", "mf", "a", "office employee {g}, {c} shirt, ID card around neck, carrying files"),
    ("peon", "Peon", "office", "m", "ao", "office peon {g}, khaki uniform, carrying a tray of tea"),
    ("raja", "Raja", "itihaas", "m", "ao", "Indian king {g}, golden crown, royal {c} sherwani, pearl necklaces"),
    ("rani", "Rani", "itihaas", "f", "ao", "Indian queen {g}, golden crown, rich {c} lehenga, jewellery"),
    ("rajkumar", "Rajkumar", "itihaas", "mf", "c", "young Indian prince or princess {g}, small crown, {c} royal clothes"),
    ("sainik", "Sainik", "itihaas", "m", "a", "ancient Indian soldier {g}, helmet, armour, {c} cloth, spear and shield"),
    ("mantri", "Mantri", "itihaas", "m", "ao", "royal minister {g}, {c} turban, long robe, rings"),
    ("rishi", "Rishi", "dharmik", "m", "o", "ancient Indian sage {g}, long white beard, {c} robe, wooden staff"),
    ("chor", "Chor", "shahar", "m", "a", "funny cartoon thief {g}, striped {c} shirt, eye mask, carrying a sack"),
    ("daku", "Daku", "gaon", "m", "a", "cartoon dacoit {g}, big moustache, {c} turban, bullet belt (kid-safe)"),
    ("jadugar", "Jadugar", "fantasy", "mf", "ao", "magician {g}, {c} cape and top hat, magic wand"),
    ("cowboy", "Cowboy", "western", "mf", "a", "cowboy {g}, {c} checked shirt, cowboy hat, boots"),
    ("western", "Western", "western", "mf", "cao", "western {g}, {c} casual clothes, friendly"),
    ("astronaut", "Astronaut", "professions", "mf", "a", "astronaut {g}, white space suit with {c} patches, helmet in hand"),
    ("sportsman", "Khiladi", "professions", "mf", "a", "Indian sports player {g}, {c} jersey, holding a cricket bat"),
    ("singer", "Gayak", "professions", "mf", "a", "singer {g}, {c} stage clothes, holding a microphone"),
]

ANIMALS = [  # id, name, look, size, voice kind
    ("sher", "Sher", "lion with golden mane", "big", "lion"), ("baagh", "Baagh", "orange tiger with black stripes", "big", "lion"),
    ("cheeta", "Cheeta", "spotted cheetah", "medium", "man"), ("haathi", "Haathi", "grey elephant with big ears and trunk", "big", "old"),
    ("bhalu", "Bhalu", "brown bear", "big", "lion"), ("bandar", "Bandar", "brown monkey with curly tail", "medium", "comic"),
    ("lomdi", "Lomdi", "orange fox with bushy tail", "medium", "villain"), ("bhediya", "Bhediya", "grey wolf", "medium", "villain"),
    ("hiran", "Hiran", "spotted deer", "medium", "woman"), ("zebra", "Zebra", "striped zebra", "medium", "man"),
    ("jiraaf", "Jiraaf", "tall giraffe with spots", "big", "comic"), ("gainda", "Gainda", "grey rhinoceros", "big", "lion"),
    ("dariyai_ghoda", "Dariyai ghoda", "chubby hippopotamus", "big", "comic"), ("oont", "Oont", "camel with a hump", "big", "old"),
    ("ghoda", "Ghoda", "brown horse", "big", "man"), ("gadha", "Gadha", "grey donkey", "medium", "comic"),
    ("gaay", "Gaay", "white cow with a bell", "big", "woman"), ("bhains", "Bhains", "black buffalo", "big", "old"),
    ("bakri", "Bakri", "white goat", "medium", "comic"), ("bhed", "Bhed", "fluffy sheep", "medium", "woman"),
    ("suar", "Suar", "pink pig", "medium", "comic"), ("kutta", "Kutta", "friendly dog", "medium", "man"),
    ("billi", "Billi", "cute cat", "small", "girl"), ("chuha", "Chuha", "tiny mouse with big ears", "small", "tiny"),
    ("khargosh", "Khargosh", "white rabbit with long ears", "small", "tiny"), ("gilhari", "Gilhari", "striped squirrel", "small", "tiny"),
    ("kachhua", "Kachhua", "slow tortoise with shell", "small", "old"), ("magarmach", "Magarmach", "green crocodile", "big", "villain"),
    ("saanp", "Saanp", "green snake", "medium", "villain"), ("mendhak", "Mendhak", "green frog", "small", "comic"),
    ("panda", "Panda", "black and white panda", "big", "comic"), ("kangaroo", "Kangaroo", "kangaroo with a pouch", "medium", "woman"),
    ("koala", "Koala", "grey koala", "small", "tiny"), ("penguin", "Penguin", "black and white penguin", "small", "comic"),
    ("sloth", "Sloth", "slow sleepy sloth", "medium", "old"), ("hedgehog", "Kantedaar chuha", "spiky hedgehog", "small", "tiny"),
    ("chamgadad", "Chamgadad", "black bat", "small", "villain"), ("lakadbagha", "Lakadbagha", "spotted hyena", "medium", "villain"),
    ("nevla", "Nevla", "brown mongoose", "small", "man"), ("gorilla", "Gorilla", "big black gorilla", "big", "lion"),
    ("chimpanzee", "Chimpanzee", "playful chimpanzee", "medium", "comic"), ("ullu_bilav", "Bilav", "big wild cat", "medium", "villain"),
    ("yak", "Yak", "hairy yak", "big", "old"), ("hiran_baby", "Hiran ka bachcha", "baby deer", "small", "girl"),
    ("dinosaur", "Dinosaur", "friendly green dinosaur", "big", "lion"), ("unicorn", "Unicorn", "white unicorn with rainbow mane", "medium", "girl"),
]

BIRDS = [("tota", "Tota", "green parrot"), ("kauwa", "Kauwa", "black crow"), ("chidiya", "Chidiya", "brown sparrow"),
         ("mor", "Mor", "peacock with long feathers"), ("ullu", "Ullu", "wise owl"), ("kabutar", "Kabutar", "grey pigeon"),
         ("bagula", "Bagula", "white crane"), ("batakh", "Batakh", "yellow duck"), ("murgi", "Murgi", "hen"), ("murga", "Murga", "rooster"),
         ("cheel", "Cheel", "brown eagle"), ("koyal", "Koyal", "black cuckoo"), ("maina", "Maina", "myna bird"),
         ("hans", "Hans", "white swan"), ("kathfodwa", "Kathfodwa", "woodpecker"), ("flamingo", "Flamingo", "pink flamingo"),
         ("toucan", "Toucan", "toucan with big colourful beak"), ("goldfinch", "Goldfinch", "small yellow finch"),
         ("titli", "Titli", "colourful butterfly"), ("madhumakhi", "Madhumakhi", "honey bee"), ("cheenti", "Cheenti", "red ant"),
         ("makdi", "Makdi", "friendly spider"), ("jugnu", "Jugnu", "glowing firefly"), ("ghonga", "Ghonga", "snail with shell"),
         ("tiddha", "Tiddha", "green grasshopper"), ("ladybug", "Ladybug", "red ladybug with spots"), ("machchhar", "Machchhar", "mosquito"),
         ("keeda", "Keeda", "green caterpillar")]

SEA = [("machhli", "Machhli", "orange fish"), ("shark", "Shark", "grey shark"), ("dolphin", "Dolphin", "blue dolphin"),
       ("whale", "Whale", "big blue whale"), ("octopus", "Octopus", "purple octopus"), ("kekda", "Kekda", "red crab"),
       ("jhinga", "Jhinga", "pink shrimp"), ("starfish", "Starfish", "orange starfish"), ("jellyfish", "Jellyfish", "glowing jellyfish"),
       ("seahorse", "Seahorse", "yellow seahorse"), ("samudri_kachhua", "Samudri kachhua", "sea turtle"), ("seal", "Seal", "grey seal")]

FANTASY = [("pari", "Pari", "fairy with sparkling wings", "f"), ("jinn", "Jinn", "blue genie from a lamp", "m"),
           ("rakshas", "Rakshas", "funny big demon with horns (kid-safe)", "m"), ("dragon", "Dragon", "friendly red dragon", "m"),
           ("robot", "Robot", "shiny friendly robot", "m"), ("alien", "Alien", "green alien with antennae", "m"),
           ("superhero", "Superhero", "superhero with cape and mask", "mf"), ("bauna", "Bauna", "small dwarf with beard", "m"),
           ("jadui_billi", "Jadui billi", "magical purple cat", "f"), ("mermaid", "Jalpari", "mermaid with fish tail", "f"),
           ("santa", "Santa", "Santa Claus with red suit", "m"), ("snowman", "Snowman", "snowman with carrot nose", "m"),
           ("gudda", "Gudda", "toy doll", "mf"), ("teddy", "Teddy", "teddy bear toy", "m"), ("yeti", "Yeti", "white furry yeti", "m")]

HORROR = [("bhoot", "Bhoot", "pale floating ghost", "mf"), ("chudail", "Chudail", "witch with wild hair", "f"),
          ("kankal", "Kankal", "funny skeleton", "m"), ("zombie", "Zombie", "green cartoon zombie (kid-safe)", "m"),
          ("vampire", "Vampire", "vampire with cape", "m"), ("tantrik", "Tantrik", "mysterious tantrik with beard", "m"),
          ("pishach", "Pishach", "shadowy creature with glowing eyes", "m"), ("mummy", "Mummy", "bandaged mummy", "m"),
          ("bhootiya_gudiya", "Bhootiya gudiya", "creepy doll", "f"), ("pumpkin", "Kaddu bhoot", "jack-o-lantern head", "m")]

FOODS = ["aloo", "pyaaz", "tamatar", "gaajar", "baingan", "bhindi", "mirchi", "lauki", "karela", "gobhi", "patta gobhi", "matar",
         "mooli", "lahsun", "adrak", "kaddu", "kheera", "shimla mirch", "aam", "kela", "seb", "angoor", "santra", "anaar",
         "tarbooz", "papita", "ananas", "nimbu", "nariyal", "jamun", "litchi", "strawberry", "samosa", "jalebi", "laddoo",
         "roti", "pizza", "burger", "ice cream", "chai cup"]

OBJECTS = ["ghadi", "chashma", "chhatri", "kitaab", "pencil", "rubber", "bag", "joota", "topi", "kursi", "mez", "palang",
           "lamp", "pankha", "TV", "mobile phone", "laptop", "radio", "camera", "cycle", "car", "bus", "train engine",
           "aeroplane", "nav", "tractor", "auto rickshaw", "scooter", "ghanti", "taala", "chaabi", "balti", "matka", "kettle",
           "cooker", "kadhai", "chammach", "glass", "botal", "gubbara", "patang", "lattoo", "football", "cricket bat",
           "guitar", "dholak", "baansuri", "seeti", "mombatti", "diya", "tijori", "sikka", "note", "khilona gaadi",
           "robot khilona", "kaanch ka marbal", "jhaadu", "baalti mug", "sabun", "toothbrush"]

PLANTS = ["bargad ka ped", "peepal ka ped", "aam ka ped", "neem ka ped", "nariyal ka ped", "khajoor ka ped", "pine ka ped",
          "bamboo", "kela ka paudha", "gulab", "kamal", "surajmukhi", "genda phool", "tulsi", "cactus", "mushroom", "ghaas ka gucchha",
          "bel", "jaadui ped", "boodha ped", "chhota paudha", "phoolon ki jhaadi", "kaante wali jhaadi", "bonsai", "sukha ped",
          "chandan ka ped", "imli ka ped", "gulmohar", "amrud ka ped", "seb ka ped"]

PLACES = [  # id-ish name, English description, keywords
    ("gaon_gali", "Gaon ki gali", "Indian village street with mud houses, thatched roofs and a big tree", "village street gaon gali"),
    ("gaon_khet", "Khet", "green farm fields with crops, a small hut and blue sky", "field farm khet crop"),
    ("gaon_kuan", "Gaon ka kuan", "village well with a pulley under a neem tree", "well kuan"),
    ("gaon_chaupal", "Chaupal", "village meeting place under a banyan tree with charpais", "chaupal panchayat meeting"),
    ("gaon_ghar_andar", "Gaon ka ghar (andar)", "inside a simple Indian village hut, clay stove, utensils, charpai", "hut inside kitchen ghar"),
    ("gaon_mela", "Gaon ka mela", "Indian village fair with stalls, giant wheel and colourful flags", "fair mela"),
    ("gaon_talab", "Talab", "village pond with lotus flowers and ducks", "pond talab lake"),
    ("gaon_mandir", "Mandir", "small Indian village temple with bells and flowers", "temple mandir"),
    ("gaon_school", "Gaon ka school", "small village school building with a playground", "village school"),
    ("gaon_raat", "Gaon (raat)", "Indian village at night with moon, stars and lanterns", "night village raat"),
    ("shahar_sadak", "Shahar ki sadak", "busy Indian city road with shops, autos and buses", "city road street traffic"),
    ("shahar_market", "Bazaar", "crowded Indian market with fruit and cloth shops", "market bazaar shop"),
    ("shahar_flat", "Flat ka kamra", "modern Indian apartment living room with sofa and TV", "living room flat apartment home"),
    ("shahar_kitchen", "Kitchen", "modern Indian kitchen with gas stove and shelves", "kitchen"),
    ("bedroom", "Bedroom", "cosy bedroom with bed, window and toys", "bedroom room bed"),
    ("school_class", "Classroom", "Indian school classroom with blackboard, desks and charts", "classroom class school"),
    ("school_ground", "School ground", "school playground with swings and a football", "playground ground school"),
    ("office", "Office", "modern office with desks, computers and glass walls", "office work"),
    ("hospital", "Hospital", "hospital room with bed, monitor and curtains", "hospital clinic doctor"),
    ("police_station", "Police station", "Indian police station with desk and lockup", "police station thana"),
    ("court", "Adalat", "Indian courtroom with judge's bench", "court adalat"),
    ("railway", "Railway station", "Indian railway platform with a train", "railway station train platform"),
    ("bus_stand", "Bus stand", "Indian bus stand with buses and benches", "bus stand"),
    ("airport", "Airport", "airport terminal with planes outside", "airport"),
    ("factory", "Factory", "big factory with machines and chimneys", "factory industry"),
    ("mill", "Mill", "old textile mill with looms", "mill"),
    ("construction", "Construction site", "building construction site with cranes", "construction site"),
    ("park", "Park", "green city park with benches, trees and a fountain", "park garden"),
    ("jungle", "Jungle", "thick green jungle with tall trees and vines", "jungle forest"),
    ("jungle_raat", "Jungle (raat)", "dark jungle at night with fireflies and moon", "night jungle forest"),
    ("nadi", "Nadi kinara", "river bank with stones, reeds and a boat", "river nadi bank"),
    ("pahad", "Pahad", "mountains with snow peaks and pine trees", "mountain pahad hill"),
    ("registan", "Registan", "desert with sand dunes and camels", "desert"),
    ("samundar", "Samundar kinara", "sunny beach with palm trees and waves", "beach sea samundar"),
    ("samundar_neeche", "Samundar ke neeche", "underwater with coral reefs and fish", "underwater ocean"),
    ("gufa", "Gufa", "dark cave with rocks and a small fire", "cave gufa"),
    ("mahal", "Mahal", "Indian royal palace hall with throne and pillars", "palace mahal throne"),
    ("qila", "Qila", "old Indian fort on a hill", "fort qila"),
    ("darbar", "Darbar", "royal court of an Indian king", "court darbar king"),
    ("ashram", "Ashram", "peaceful forest ashram with huts", "ashram"),
    ("bhootiya_haveli", "Bhootiya haveli", "spooky old mansion at night with bats", "haunted mansion bhootiya horror"),
    ("kabristan", "Kabristan", "spooky graveyard at night with fog (kid-safe)", "graveyard"),
    ("space", "Antariksh", "outer space with planets and stars", "space"),
    ("chand", "Chand", "surface of the moon with craters", "moon"),
    ("jaadui_jungle", "Jaadui jungle", "magical glowing forest with giant mushrooms", "magic forest fairy"),
    ("baraf", "Barf", "snowy land with igloo", "snow ice"),
    ("cricket_ground", "Cricket ground", "cricket stadium with crowd", "cricket stadium match"),
    ("library_place", "Library", "library with tall bookshelves", "library books"),
    ("restaurant", "Dhaba", "Indian roadside dhaba with charpais and trucks", "dhaba restaurant food"),
    ("shaadi", "Shaadi ka mandap", "decorated Indian wedding venue with lights", "wedding shaadi"),
]

SIZE_BY_AGE = {"c": "small", "a": "medium", "o": "medium"}


def _h(s: str) -> int:
    return int(hashlib.md5(s.encode("utf-8")).hexdigest()[:8], 16)


def design_voice(gender: str, age: str, size: str = "medium", kind: str = "human", seed: str = "") -> tuple[str, list[int]]:
    """Pick a base voice and a pitch / speed change that suits the character (each id sounds a bit different)."""
    j = _h(seed) % 3 - 1  # -1, 0, +1 small personal difference
    if kind in ("tiny",) or size == "small" and kind not in ("human",):
        return "hi-tiny", [5 + j, 12]
    if kind == "lion" or (size == "big" and kind not in ("human", "woman", "girl", "comic", "old")):
        return "hi-lion", [-3 + j, -8]
    if kind == "villain":
        return "hi-villain", [j, -4]
    if kind == "comic":
        return "hi-comic", [1 + j, 6]
    if age == "c":
        return ("hi-girl" if gender == "f" else "hi-boy"), [1 + j, 4]
    if age == "o" or kind == "old":
        return ("hi-old-woman" if gender == "f" else "hi-old-man"), [j, -6]
    if kind == "girl":
        return "hi-girl", [j, 2]
    if kind == "woman":
        return "hi-woman", [j, 0]
    return ("hi-woman" if gender == "f" else "hi-man"), [j, 0]


def build() -> list[dict]:
    out: list[dict] = []

    seen: set[str] = set()

    def add(eid, name, cat, gender, age, size, look, vkind="human", kind="actor", keywords=""):
        if eid in seen:
            return
        seen.add(eid)
        voice, tune = design_voice(gender, age, size, vkind, eid)
        out.append({"id": eid, "name": name, "category": cat, "kind": kind, "gender": gender, "age": {"c": "child", "a": "adult", "o": "old"}.get(age, age),
                    "size": size, "voice": voice, "tune": tune, "look": look, "keywords": keywords})

    for rid, label, cat, genders, ages, look in HUMANS:
        n = 0
        for g in genders:
            for a in ages:
                for ci, c in enumerate(COLORS):
                    pool = (BOY if g == "m" else GIRL) if a == "c" else (OLD_M if g == "m" else OLD_F) if a == "o" else (MALE if g == "m" else FEMALE)
                    pname = pool[(_h(rid) + n) % len(pool)]
                    word = {"c": "boy" if g == "m" else "girl", "a": "man" if g == "m" else "woman", "o": "old man" if g == "m" else "old woman"}[a]
                    add(f"h_{rid}_{g}{a}{ci}", f"{pname} ({label})", cat, g, a, SIZE_BY_AGE[a], look.format(c=c, g=word))
                    n += 1
    for aid, name, look, size, vk in ANIMALS:
        add(f"a_{aid}", name, "animals", "m", "a", size, f"cartoon {look}, standing, friendly face", vk)
        add(f"a_{aid}_baby", f"{name} ka bachcha", "animals", "f", "c", "small", f"cute baby cartoon {look}, big eyes", "tiny")
    for bid, name, look in BIRDS:
        cat = "birds" if bid in [b[0] for b in BIRDS[:18]] else "keede"
        add(f"b_{bid}", name, cat, "m", "a", "small", f"cartoon {look} with a friendly face", "tiny" if cat == "keede" else "comic")
        add(f"b_{bid}_2", f"{name} (2)", cat, "f", "c", "small", f"cute cartoon {look}, different colours, big eyes", "tiny")
    for sid, name, look in SEA:
        add(f"s_{sid}", name, "samundar", "m", "a", "medium" if sid in ("shark", "whale", "dolphin") else "small", f"cartoon {look} with a friendly face",
            "lion" if sid in ("shark", "whale") else "comic")
    for fid, name, look, genders in FANTASY:
        for g in genders:
            add(f"f_{fid}_{g}", name, "fantasy", g, "a", "medium", f"cartoon {look}", "woman" if g == "f" else "man")
    for hid, name, look, genders in HORROR:
        for g in genders:
            add(f"x_{hid}_{g}", name, "horror", g, "a", "medium", f"spooky but kid-safe cartoon {look}", "villain")
    for i, food in enumerate(FOODS):
        add(f"v_{i}", f"{food.title()}", "sabzi-phal", "mf"[i % 2], "a", "small", f"cute cartoon {food} character with face, little arms and legs, standing",
            "comic" if i % 3 else "tiny")
    for i, obj in enumerate(OBJECTS):
        add(f"o_{i}", f"{obj.title()}", "cheezein", "mf"[i % 2], "a", "small", f"cute cartoon {obj} character with a face, little arms and legs, standing",
            "comic")
    for i, pl in enumerate(PLANTS):
        add(f"p_{i}", f"{pl.title()}", "ped-paudhe", "m" if "ped" in pl else "f", "o" if "boodha" in pl or "bargad" in pl else "a",
            "big" if "ped" in pl else "small", f"cartoon {pl} with a friendly face", "old" if "ped" in pl else "tiny")
    for pid, name, desc, kw in PLACES:
        for tod, word in (("", ""), ("_raat", " at night")):
            if pid.endswith("raat") and tod:
                continue
            add(f"pl_{pid}{tod}", name + (" (raat)" if tod else ""), "jagah", "m", "a", "big", desc + word, kind="place", keywords=kw)
    return out
