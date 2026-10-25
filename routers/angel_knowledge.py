"""
Angel knowledge: full lead-word dictionary + short KJV-rooted teaching paragraphs.
Sources Angel may use (in priority):
  1. General Admin Angel resources (any category, including kwealth)
  2. Built-in Scripture teaching for matched lead words
  3. Gentle gospel tether when relevant
"""
from typing import List, Dict, Tuple

# Full lead dictionary (normalized lowercase, multi-word kept with spaces)
LEAD_WORDS: List[str] = [
    # A
    "abaddon", "abomination", "abraham", "absolution", "adoption", "adultery", "advocate",
    "affliction", "afterlife", "altar", "amen", "angels", "anointing", "anointed", "apostles",
    "apostleship", "ark of the covenant", "ascension", "atonement", "authority", "awakening",
    "acknowledgment", "assurance", "antichrist", "armageddon", "asceticism", "adoption as sons",
    "angels of god", "answered prayer",
    # B
    "baptism", "beatitudes", "belief", "believing", "bible", "scripture", "blasphemy", "blessing",
    "blood of christ", "blood covenant", "born again", "bread of life", "bride of christ",
    "bridegroom", "brotherhood", "burning bush", "burnt offering", "bondage", "body of christ",
    "book of life", "books of moses", "babylon", "balaam", "barabbas", "bethlehem", "beatification",
    "benevolence",
    # C
    "calling", "calvary", "canaan", "canon", "carnality", "charity", "christ", "christian",
    "church", "circumcision", "commandments", "communion", "confession", "conscience",
    "consecration", "covenant", "creation", "creator", "cross", "crucifixion", "crown of life",
    "curse", "conversion", "conviction", "corruption", "comforter", "communion with god",
    "covenant theology", "clean", "unclean", "cities of refuge", "civil law", "ceremonial law",
    # D
    "daniel", "david", "day of atonement", "death", "deacon", "deity of christ", "deliverance",
    "demons", "devils", "denial", "destruction", "discipleship", "discipline", "divorce",
    "doctrine", "dominion", "doubt", "dreams", "duties", "day of judgment", "dead works",
    "divine judgment", "divine providence", "depravity", "deuteronomy", "dietary laws",
    # E
    "eden", "egypt", "election", "elijah", "elisha", "emmanuel", "end times", "eternal life",
    "eternal punishment", "evangelism", "evangelist", "exodus", "exorcism", "expiation",
    "exaltation", "example of christ", "elders", "epistles", "eschatology", "everlasting covenant",
    "evil", "enemies", "evidence of faith", "everlasting fire",
    # F
    "faith", "faithfulness", "fall of man", "father", "fasting", "fear of god", "fellowship",
    "forgiveness", "fornication", "free will", "fruit of the spirit", "firstfruits", "firstborn",
    "flesh", "fulfilment of prophecy", "final judgment", "false prophets", "false teachers",
    "false christ", "feasts of israel", "feast of passover", "feast of pentecost",
    "feast of tabernacles", "feast of trumpets", "feast of unleavened bread", "faithful servant",
    "foundation",
    # G
    "gabriel", "garden of eden", "gentiles", "glory of god", "gospel", "grace", "gratitude",
    "great commission", "great tribulation", "god", "godhead", "good works", "good shepherd",
    "golden calf", "gifts of the spirit", "giving", "genealogy", "gehenna", "gethsemane",
    "generosity", "gentile salvation", "glorification", "godliness", "grace through faith",
    # H
    "hades", "hell", "hallelujah", "heaven", "hebrew", "hebrews", "holy ghost", "holy spirit",
    "holiness", "holy place", "holy of holies", "holy scriptures", "holy covenant", "hope",
    "hosanna", "humility", "hypocrisy", "healing", "heresy", "high priest", "head of the church",
    "heavenly jerusalem", "heavenly father", "house of god", "house of israel", "house of david",
    "holy communion", "holiness of god",
    # I
    "immanuel", "image of god", "immortality", "imputation", "incarnation", "iniquity",
    "inspiration", "intercession", "israel", "israelites", "isaac", "jacob", "idolatry", "idols",
    "indwelling spirit", "inheritance", "incense", "infants", "inner man", "inner holiness",
    "israel's covenant", "isaiah", "i am",
    # J
    "jehovah", "jerusalem", "jesus", "jesus christ", "jews", "judaism", "judgment",
    "judgment seat of christ", "justification", "jubilee", "joseph", "john the baptist",
    "john the apostle", "jordan river", "joshua", "joy", "jealousy of god", "jewish law",
    "jewish feasts", "jewish priesthood", "jewish temple", "jerusalem council",
    "jesus as messiah", "jesus as king", "jesus as lord",
    # K
    "kingdom of god", "kingdom of heaven", "king", "kingship", "knowledge of god",
    "knowledge of scripture", "keys of the kingdom", "kinsman redeemer", "korah", "kadesh",
    "keeping commandments", "knowing christ", "knowing god",
    # L
    "lamb of god", "law", "law of moses", "levitical law", "levites", "leviticus", "life",
    "light", "lord", "lord's supper", "love", "love of god", "love of neighbour", "lucifer",
    "laying on of hands", "last days", "last judgment", "last supper", "last adam",
    "living water", "living sacrifice", "lamb's book of life", "legalism", "liberty in christ",
    "longsuffering",
    # M
    "messiah", "messianic prophecy", "moses", "mosaic covenant", "mosaic law", "manna",
    "marriage", "mercy", "miracles", "ministry", "ministers", "ministry gifts", "mission",
    "martyrdom", "melchisedec", "mount sinai", "mount zion", "mount of olives", "monotheism",
    "morality", "murder", "modesty", "maturity", "man", "man of sin", "mark of the beast",
    "millennium", "mediation", "mediator", "mercy seat",
    # N
    "name of god", "name of jesus", "nazarene", "nazareth", "new birth", "new covenant",
    "new creation", "new jerusalem", "new heaven", "new earth", "new testament", "noah",
    "noah's ark", "numbers", "nazarite", "neighbour", "nation", "nations", "natural man",
    "new commandment", "new heart", "new life", "new man", "nicodemus",
    # O
    "obedience", "offering", "old covenant", "old testament", "omnipotence", "omnipresence",
    "omniscience", "original sin", "ordinances", "ordination", "overcoming", "oil", "olive oil",
    "olive tree", "one god", "one body", "one faith", "one baptism", "one lord",
    "obedience of faith", "offerings", "oaths", "oracles of god",
    # P
    "passover", "pentecost", "prayer", "praise", "predestination", "prophecy", "prophet",
    "priest", "priesthood", "propitiation", "purification", "purity", "providence",
    "providence of god", "psalms", "paul", "peter", "pharisees", "pilate", "paradise",
    "parables", "persecution", "patience", "peace", "peace with god", "perfecting holiness",
    "promise", "promised land", "promises of god", "principalities", "powers", "pastors",
    "preaching", "poor", "purity of heart", "plagues", "potter and clay",
    # Q
    "questions of faith", "quenching the spirit", "quickening", "quietness", "quail",
    "queen of sheba", "qualified ministers", "quicken", "quarrelling",
    # R
    "rapture", "redemption", "redeemer", "regeneration", "repentance", "resurrection",
    "resurrection of christ", "resurrection of the dead", "revelation", "righteousness",
    "righteousness by faith", "righteous judgment", "royal priesthood", "rock of salvation",
    "roaring lion", "romans", "ruth", "revelation of god", "reconciliation",
    "reconciliation with god", "rest", "restitution", "restoration", "remission of sins",
    "riches", "riches in christ", "river jordan", "refuge", "reward", "resurrection body",
    # S
    "sabbath", "sacrifice", "salvation", "sanctification", "sanctuary", "satan", "scripture",
    "second coming", "seed", "serpent", "sin", "sins", "son of god", "son of man", "spirit",
    "spiritual gifts", "spiritual warfare", "spiritual body", "spiritual israel",
    "spiritual growth", "submission", "suffering", "supplication", "stewardship", "saints",
    "shepherd", "sheep", "sermon on the mount", "sinai", "saviour", "sovereignty of god",
    "separation", "service", "servant", "seven churches", "seven seals", "seven trumpets",
    "seven bowls", "sheol", "shiloh", "shofar", "shalom", "synagogue", "sanhedrin",
    "sadducees", "scribes", "spirit of adoption", "spirit of truth", "spirit of prophecy",
    "spiritual fruit", "spiritual house", "stone tablets", "salt of the earth", "second death",
    # T
    "tabernacle", "temple", "ten commandments", "tithes", "tithing", "torah", "transfiguration",
    "trinity", "tribulation", "trespass", "trial", "truth", "thanksgiving", "testimony",
    "temptation", "temptation of christ", "teacher", "teaching", "tongues", "tongues of fire",
    "tree of life", "tree of knowledge", "trespasses", "trumpet", "trumpets", "two witnesses",
    "twelve apostles", "twelve tribes", "talents", "treasure in heaven", "transgression",
    "tradition", "traditions of men", "temple worship", "temple veil", "total depravity",
    # U
    "unbelief", "unclean spirits", "unleavened bread", "understanding", "unity",
    "unity of believers", "universal church", "urim and thummim", "usury", "uprightness",
    "undivided heart", "unforgivable sin", "unsearchable riches", "under the law",
    "under grace", "upper room",
    # V
    "vain worship", "vanity", "vengeance", "victory", "vine", "vineyard", "virgin birth",
    "virgin mary", "vision", "vocation", "vow", "vows", "veil", "veil of the temple",
    "violence", "virtue", "voice of god", "voluntary offerings", "vessels", "vessels of mercy",
    "vessels of wrath",
    # W
    "walk with god", "walking in the spirit", "warfare", "water baptism", "washing",
    "watchfulness", "watchman", "way", "word of god", "word made flesh", "worship",
    "wrath of god", "works", "works of the flesh", "works of righteousness", "works of the law",
    "witness", "witnesses", "wisdom", "wisdom of god", "wilderness", "will of god",
    "will of the father", "widow", "widow's offering", "washing of regeneration",
    "white throne", "white garments", "wheat and tares", "wine", "winepress", "wages of sin",
    "worldliness",
    # X Y Z
    "xerxes", "yahweh", "year of jubilee", "yoke", "yoke of christ", "yom kippur", "young men",
    "youth", "year of release", "year of rest", "your neighbour", "zeal", "zechariah",
    "zephaniah", "zerubbabel", "zion", "zacchaeus", "zacharias", "zedekiah", "zealots",
]

# Short conversational teachings keyed by primary lead word (KJV-rooted)
TOPIC_TEACHINGS: Dict[str, str] = {
    "faith": (
        "Faith is the substance of things hoped for, the evidence of things not seen (Hebrews 11:1). "
        "Without faith it is impossible to please God (Hebrews 11:6). "
        "We are saved by grace through faith, and that not of ourselves: it is the gift of God (Ephesians 2:8-9). "
        "Faith comes by hearing, and hearing by the word of God (Romans 10:17)."
    ),
    "prayer": (
        "Jesus taught us to pray: Our Father which art in heaven, Hallowed be thy name (Matthew 6:9). "
        "Let us therefore come boldly unto the throne of grace, that we may obtain mercy (Hebrews 4:16). "
        "If we confess our sins, he is faithful and just to forgive us our sins (1 John 1:9). "
        "Ask, and it shall be given you; seek, and ye shall find (Matthew 7:7)."
    ),
    "salvation": (
        "God so loved the world, that he gave his only begotten Son, that whosoever believeth in him should not perish, but have everlasting life (John 3:16). "
        "All have sinned, and come short of the glory of God (Romans 3:23). "
        "The wages of sin is death; but the gift of God is eternal life through Jesus Christ our Lord (Romans 6:23). "
        "If thou shalt confess with thy mouth the Lord Jesus, and shalt believe in thine heart that God hath raised him from the dead, thou shalt be saved (Romans 10:9)."
    ),
    "jesus": (
        "Jesus is the Christ, the Son of the living God (Matthew 16:16). "
        "In the beginning was the Word, and the Word was with God, and the Word was God… And the Word was made flesh (John 1:1, 14). "
        "Neither is there salvation in any other: for there is none other name under heaven given among men, whereby we must be saved (Acts 4:12). "
        "Christ died for our sins according to the scriptures; and that he was buried, and that he rose again the third day (1 Corinthians 15:3-4)."
    ),
    "jesus christ": (
        "Jesus Christ is the same yesterday, and to day, and for ever (Hebrews 13:8). "
        "There is one God, and one mediator between God and men, the man Christ Jesus (1 Timothy 2:5). "
        "He is the Lamb of God, which taketh away the sin of the world (John 1:29)."
    ),
    "holy spirit": (
        "The Comforter, which is the Holy Ghost, whom the Father will send in my name, he shall teach you all things (John 14:26). "
        "And when he is come, he will reprove the world of sin, and of righteousness, and of judgment (John 16:8). "
        "Ye shall receive power, after that the Holy Ghost is come upon you (Acts 1:8). "
        "Be filled with the Spirit (Ephesians 5:18). The fruit of the Spirit is love, joy, peace, longsuffering, gentleness, goodness, faith, meekness, temperance (Galatians 5:22-23)."
    ),
    "holy ghost": (
        "The Holy Ghost is the Comforter sent by the Father in Jesus' name (John 14:26). "
        "By one Spirit are we all baptized into one body (1 Corinthians 12:13). "
        "If ye then, being evil, know how to give good gifts unto your children: how much more shall your heavenly Father give the Holy Spirit to them that ask him? (Luke 11:13)."
    ),
    "grace": (
        "For by grace are ye saved through faith; and that not of yourselves: it is the gift of God (Ephesians 2:8). "
        "Where sin abounded, grace did much more abound (Romans 5:20). "
        "The grace of God that bringeth salvation hath appeared to all men, teaching us that, denying ungodliness and worldly lusts, we should live soberly, righteously, and godly (Titus 2:11-12)."
    ),
    "repentance": (
        "Repent ye therefore, and be converted, that your sins may be blotted out (Acts 3:19). "
        "Godly sorrow worketh repentance to salvation not to be repented of (2 Corinthians 7:10). "
        "Except ye repent, ye shall all likewise perish (Luke 13:3)."
    ),
    "resurrection": (
        "It is sown in corruption; it is raised in incorruption (1 Corinthians 15:42). "
        "Behold, I shew you a mystery; We shall not all sleep, but we shall all be changed, in a moment, in the twinkling of an eye, at the last trump (1 Corinthians 15:51-52). "
        "The Lord himself shall descend from heaven with a shout… and the dead in Christ shall rise first (1 Thessalonians 4:16)."
    ),
    "heaven": (
        "In my Father's house are many mansions… I go to prepare a place for you (John 14:2). "
        "And God shall wipe away all tears from their eyes; and there shall be no more death, neither sorrow, nor crying (Revelation 21:4). "
        "And there shall in no wise enter into it any thing that defileth (Revelation 21:27)."
    ),
    "hell": (
        "Jesus warned of hell fire, where their worm dieth not, and the fire is not quenched (Mark 9:43-44). "
        "And death and hell were cast into the lake of fire. This is the second death (Revelation 20:14). "
        "Yet the greater word is mercy: Christ is able to save them to the uttermost that come unto God by him (Hebrews 7:25)."
    ),
    "church": (
        "Christ is the head of the church: and he is the saviour of the body (Ephesians 5:23). "
        "Upon this rock I will build my church; and the gates of hell shall not prevail against it (Matthew 16:18). "
        "Not forsaking the assembling of ourselves together (Hebrews 10:25)."
    ),
    "love": (
        "God is love (1 John 4:8). "
        "Thou shalt love the Lord thy God with all thy heart… and thy neighbour as thyself (Matthew 22:37-39). "
        "Charity suffereth long, and is kind… Charity never faileth (1 Corinthians 13:4, 8)."
    ),
    "forgiveness": (
        "If we confess our sins, he is faithful and just to forgive us our sins, and to cleanse us from all unrighteousness (1 John 1:9). "
        "And be ye kind one to another, tenderhearted, forgiving one another, even as God for Christ's sake hath forgiven you (Ephesians 4:32)."
    ),
    "cross": (
        "God forbid that I should glory, save in the cross of our Lord Jesus Christ (Galatians 6:14). "
        "Who his own self bare our sins in his own body on the tree (1 Peter 2:24). "
        "It is finished (John 19:30)."
    ),
    "gospel": (
        "Christ died for our sins according to the scriptures; and that he was buried, and that he rose again the third day according to the scriptures (1 Corinthians 15:3-4). "
        "For I am not ashamed of the gospel of Christ: for it is the power of God unto salvation to every one that believeth (Romans 1:16)."
    ),
    "baptism": (
        "Go ye therefore, and teach all nations, baptizing them in the name of the Father, and of the Son, and of the Holy Ghost (Matthew 28:19). "
        "Repent, and be baptized every one of you in the name of Jesus Christ for the remission of sins (Acts 2:38). "
        "Therefore we are buried with him by baptism into death (Romans 6:4)."
    ),
    "covenant": (
        "This is my blood of the new testament, which is shed for many for the remission of sins (Matthew 26:28). "
        "Behold, the days come, saith the Lord, that I will make a new covenant with the house of Israel (Jeremiah 31:31; Hebrews 8:8)."
    ),
    "sin": (
        "Sin is the transgression of the law (1 John 3:4). "
        "All have sinned, and come short of the glory of God (Romans 3:23). "
        "If we say that we have no sin, we deceive ourselves (1 John 1:8). "
        "But if we walk in the light… the blood of Jesus Christ his Son cleanseth us from all sin (1 John 1:7)."
    ),
    "word of god": (
        "Thy word is a lamp unto my feet, and a light unto my path (Psalm 119:105). "
        "All scripture is given by inspiration of God, and is profitable for doctrine, for reproof, for correction, for instruction in righteousness (2 Timothy 3:16). "
        "The word of God is quick, and powerful, and sharper than any twoedged sword (Hebrews 4:12)."
    ),
    "bible": (
        "Search the scriptures; for in them ye think ye have eternal life: and they are they which testify of me (John 5:39). "
        "All scripture is given by inspiration of God (2 Timothy 3:16). "
        "Man shall not live by bread alone, but by every word that proceedeth out of the mouth of God (Matthew 4:4)."
    ),
    "scripture": (
        "All scripture is given by inspiration of God (2 Timothy 3:16). "
        "Knowing this first, that no prophecy of the scripture is of any private interpretation (2 Peter 1:20)."
    ),
    "worship": (
        "God is a Spirit: and they that worship him must worship him in spirit and in truth (John 4:24). "
        "O worship the Lord in the beauty of holiness (Psalm 96:9). "
        "Thou shalt worship the Lord thy God, and him only shalt thou serve (Matthew 4:10)."
    ),
    "hope": (
        "Which hope we have as an anchor of the soul, both sure and stedfast (Hebrews 6:19). "
        "Looking for that blessed hope, and the glorious appearing of the great God and our Saviour Jesus Christ (Titus 2:13)."
    ),
    "second coming": (
        "This same Jesus, which is taken up from you into heaven, shall so come in like manner as ye have seen him go into heaven (Acts 1:11). "
        "Behold, he cometh with clouds; and every eye shall see him (Revelation 1:7)."
    ),
    "rapture": (
        "The Lord himself shall descend from heaven with a shout… and the dead in Christ shall rise first: Then we which are alive and remain shall be caught up together with them in the clouds (1 Thessalonians 4:16-17)."
    ),
    "angels": (
        "Are they not all ministering spirits, sent forth to minister for them who shall be heirs of salvation? (Hebrews 1:14). "
        "Bless the Lord, ye his angels, that excel in strength, that do his commandments (Psalm 103:20). "
        "See thou do it not: for I am thy fellowservant… worship God (Revelation 22:9)."
    ),
    "satan": (
        "Be sober, be vigilant; because your adversary the devil, as a roaring lion, walketh about, seeking whom he may devour (1 Peter 5:8). "
        "Put on the whole armour of God, that ye may be able to stand against the wiles of the devil (Ephesians 6:11)."
    ),
    "kingdom of god": (
        "The kingdom of God is not meat and drink; but righteousness, and peace, and joy in the Holy Ghost (Romans 14:17). "
        "Seek ye first the kingdom of God, and his righteousness (Matthew 6:33)."
    ),
    "mercy": (
        "The Lord is merciful and gracious, slow to anger, and plenteous in mercy (Psalm 103:8). "
        "Blessed are the merciful: for they shall obtain mercy (Matthew 5:7)."
    ),
    "peace": (
        "Peace I leave with you, my peace I give unto you (John 14:27). "
        "And the peace of God, which passeth all understanding, shall keep your hearts and minds through Christ Jesus (Philippians 4:7)."
    ),
    "holiness": (
        "Be ye holy; for I am holy (1 Peter 1:16). "
        "Follow peace with all men, and holiness, without which no man shall see the Lord (Hebrews 12:14)."
    ),
    "sanctification": (
        "This is the will of God, even your sanctification (1 Thessalonians 4:3). "
        "And the very God of peace sanctify you wholly (1 Thessalonians 5:23)."
    ),
    "tithes": (
        "Bring ye all the tithes into the storehouse, that there may be meat in mine house (Malachi 3:10). "
        "Honour the Lord with thy substance, and with the firstfruits of all thine increase (Proverbs 3:9)."
    ),
    "tithing": (
        "Bring ye all the tithes into the storehouse (Malachi 3:10). "
        "Give, and it shall be given unto you (Luke 6:38)."
    ),
    "passover": (
        "Christ our passover is sacrificed for us (1 Corinthians 5:7). "
        "When I see the blood, I will pass over you (Exodus 12:13)."
    ),
    "atonement": (
        "Herein is love, not that we loved God, but that he loved us, and sent his Son to be the propitiation for our sins (1 John 4:10). "
        "We also joy in God through our Lord Jesus Christ, by whom we have now received the atonement (Romans 5:11)."
    ),
    "redemption": (
        "In whom we have redemption through his blood, the forgiveness of sins, according to the riches of his grace (Ephesians 1:7)."
    ),
    "justification": (
        "Being justified freely by his grace through the redemption that is in Christ Jesus (Romans 3:24). "
        "Therefore being justified by faith, we have peace with God through our Lord Jesus Christ (Romans 5:1)."
    ),
    "god": (
        "In the beginning God created the heaven and the earth (Genesis 1:1). "
        "Hear, O Israel: The Lord our God is one Lord (Deuteronomy 6:4). "
        "God is a Spirit: and they that worship him must worship him in spirit and in truth (John 4:24)."
    ),
    "father": (
        "Our Father which art in heaven, Hallowed be thy name (Matthew 6:9). "
        "Behold, what manner of love the Father hath bestowed upon us, that we should be called the sons of God (1 John 3:1)."
    ),
    "messiah": (
        "We have found the Messias, which is, being interpreted, the Christ (John 1:41). "
        "Thou art the Christ, the Son of the living God (Matthew 16:16)."
    ),
    "lamb of god": (
        "Behold the Lamb of God, which taketh away the sin of the world (John 1:29)."
    ),
    "born again": (
        "Except a man be born again, he cannot see the kingdom of God (John 3:3). "
        "Being born again, not of corruptible seed, but of incorruptible, by the word of God (1 Peter 1:23)."
    ),
    "new birth": (
        "Except a man be born of water and of the Spirit, he cannot enter into the kingdom of God (John 3:5)."
    ),
    "revelation": (
        "The Revelation of Jesus Christ, which God gave unto him, to shew unto his servants things which must shortly come to pass (Revelation 1:1). "
        "Blessed is he that readeth, and they that hear the words of this prophecy (Revelation 1:3)."
    ),
    "antichrist": (
        "Little children, it is the last time: and as ye have heard that antichrist shall come, even now are there many antichrists (1 John 2:18). "
        "Who is a liar but he that denieth that Jesus is the Christ? He is antichrist, that denieth the Father and the Son (1 John 2:22)."
    ),
    "paul": (
        "Paul preached Christ crucified (1 Corinthians 1:23). "
        "By the grace of God I am what I am (1 Corinthians 15:10). "
        "I am crucified with Christ: nevertheless I live; yet not I, but Christ liveth in me (Galatians 2:20)."
    ),
    "moses": (
        "The Lord spake unto Moses face to face, as a man speaketh unto his friend (Exodus 33:11). "
        "For the law was given by Moses, but grace and truth came by Jesus Christ (John 1:17)."
    ),
    "law": (
        "The law was our schoolmaster to bring us unto Christ, that we might be justified by faith (Galatians 3:24). "
        "Love is the fulfilling of the law (Romans 13:10)."
    ),
    "communion": (
        "This is my body which is given for you: this do in remembrance of me… This cup is the new testament in my blood (Luke 22:19-20). "
        "For as often as ye eat this bread, and drink this cup, ye do shew the Lord's death till he come (1 Corinthians 11:26)."
    ),
    "lord's supper": (
        "The Lord Jesus the same night in which he was betrayed took bread… This is my body, which is broken for you (1 Corinthians 11:23-24)."
    ),
    "temptation": (
        "There hath no temptation taken you but such as is common to man: but God is faithful, who will not suffer you to be tempted above that ye are able (1 Corinthians 10:13). "
        "Watch and pray, that ye enter not into temptation (Matthew 26:41)."
    ),
    "spiritual warfare": (
        "For we wrestle not against flesh and blood, but against principalities, against powers, against the rulers of the darkness of this world (Ephesians 6:12). "
        "Put on the whole armour of God (Ephesians 6:11)."
    ),
    "spiritual gifts": (
        "Now there are diversities of gifts, but the same Spirit (1 Corinthians 12:4). "
        "But the manifestation of the Spirit is given to every man to profit withal (1 Corinthians 12:7)."
    ),
    "fruit of the spirit": (
        "The fruit of the Spirit is love, joy, peace, longsuffering, gentleness, goodness, faith, meekness, temperance (Galatians 5:22-23)."
    ),
    "obedience": (
        "To obey is better than sacrifice (1 Samuel 15:22). "
        "If ye love me, keep my commandments (John 14:15)."
    ),
    "discipleship": (
        "If any man will come after me, let him deny himself, and take up his cross, and follow me (Matthew 16:24). "
        "Go ye therefore, and teach all nations (Matthew 28:19)."
    ),
    "evangelism": (
        "Go ye into all the world, and preach the gospel to every creature (Mark 16:15). "
        "Ye shall be witnesses unto me (Acts 1:8)."
    ),
    "great commission": (
        "Go ye therefore, and teach all nations, baptizing them… Teaching them to observe all things whatsoever I have commanded you (Matthew 28:19-20)."
    ),
    "creation": (
        "In the beginning God created the heaven and the earth (Genesis 1:1). "
        "All things were made by him; and without him was not any thing made that was made (John 1:3)."
    ),
    "trinity": (
        "The grace of the Lord Jesus Christ, and the love of God, and the communion of the Holy Ghost, be with you all (2 Corinthians 13:14). "
        "Baptizing them in the name of the Father, and of the Son, and of the Holy Ghost (Matthew 28:19)."
    ),
    "judgment": (
        "It is appointed unto men once to die, but after this the judgment (Hebrews 9:27). "
        "We must all appear before the judgment seat of Christ (2 Corinthians 5:10)."
    ),
    "eternal life": (
        "And this is life eternal, that they might know thee the only true God, and Jesus Christ, whom thou hast sent (John 17:3). "
        "He that believeth on the Son hath everlasting life (John 3:36)."
    ),
}



# --- Expanded doctrinal coverage (KJV-rooted short teachings) ---
_TOPIC_EXTRA = {
    "abaddon": "Abaddon is named as the angel of the bottomless pit (Revelation 9:11). Scripture shows judgment is real, yet the Lord Jesus holds the keys of hell and of death (Revelation 1:18).",
    "abomination": "An abomination is that which the Lord hates. Pride, a lying tongue, hands that shed innocent blood, a heart that deviseth wicked imaginations, feet that be swift in running to mischief, a false witness, and he that soweth discord among brethren (Proverbs 6:16–19).",
    "abraham": "Abraham believed God, and it was counted unto him for righteousness (Genesis 15:6; Romans 4:3). He is the father of all them that believe (Romans 4:11).",
    "adoption": "Ye have received the Spirit of adoption, whereby we cry, Abba, Father (Romans 8:15). God sent forth his Son… that we might receive the adoption of sons (Galatians 4:4–5).",
    "adultery": "Thou shalt not commit adultery (Exodus 20:14). Whosoever looketh on a woman to lust after her hath committed adultery with her already in his heart (Matthew 5:28).",
    "advocate": "If any man sin, we have an advocate with the Father, Jesus Christ the righteous (1 John 2:1).",
    "altar": "An altar of earth thou shalt make unto me (Exodus 20:24). We have an altar, whereof they have no right to eat which serve the tabernacle (Hebrews 13:10).",
    "amen": "Amen means so be it — the faithful agreement of the heart. For all the promises of God in him are yea, and in him Amen (2 Corinthians 1:20).",
    "anointing": "The anointing which ye have received of him abideth in you (1 John 2:27). God anointed Jesus of Nazareth with the Holy Ghost and with power (Acts 10:38).",
    "apostles": "He gave some, apostles; and some, prophets… for the perfecting of the saints (Ephesians 4:11–12). Built upon the foundation of the apostles and prophets, Jesus Christ himself being the chief corner stone (Ephesians 2:20).",
    "ark of the covenant": "The ark of the covenant held the testimony; over it the cherubims of glory shadowing the mercyseat (Hebrews 9:4–5). Christ is our mercy seat by faith in his blood (Romans 3:25).",
    "ascension": "While they beheld, he was taken up; and a cloud received him out of their sight (Acts 1:9). He sat down on the right hand of the Majesty on high (Hebrews 1:3).",
    "atonement": "It is the blood that maketh an atonement for the soul (Leviticus 17:11). Christ… put away sin by the sacrifice of himself (Hebrews 9:26).",
    "authority": "All power is given unto me in heaven and in earth (Matthew 28:18). Submit yourselves to every ordinance of man for the Lord’s sake (1 Peter 2:13).",
    "antichrist": "He is antichrist, that denieth the Father and the Son (1 John 2:22). That man of sin… who opposeth and exalteth himself above all that is called God (2 Thessalonians 2:3–4).",
    "armageddon": "He gathered them together into a place called in the Hebrew tongue Armageddon (Revelation 16:16). The Lord shall consume the Wicked with the spirit of his mouth (2 Thessalonians 2:8).",
    "baptism": "Go ye therefore… baptizing them in the name of the Father, and of the Son, and of the Holy Ghost (Matthew 28:19). Buried with him by baptism into death (Romans 6:4).",
    "beatitudes": "Blessed are the poor in spirit… Blessed are they that mourn… Blessed are the meek… Blessed are they which do hunger and thirst after righteousness (Matthew 5:3–6).",
    "belief": "Believe on the Lord Jesus Christ, and thou shalt be saved (Acts 16:31). He that believeth on the Son hath everlasting life (John 3:36).",
    "bible": "All scripture is given by inspiration of God, and is profitable for doctrine, for reproof, for correction, for instruction in righteousness (2 Timothy 3:16).",
    "scripture": "The holy scriptures… are able to make thee wise unto salvation through faith which is in Christ Jesus (2 Timothy 3:15).",
    "blasphemy": "Thou shalt not take the name of the Lord thy God in vain (Exodus 20:7). All manner of sin and blasphemy shall be forgiven unto men: but the blasphemy against the Holy Ghost shall not be forgiven (Matthew 12:31).",
    "blessing": "The blessing of the Lord, it maketh rich, and he addeth no sorrow with it (Proverbs 10:22).",
    "blood of christ": "The blood of Jesus Christ his Son cleanseth us from all sin (1 John 1:7). Without shedding of blood is no remission (Hebrews 9:22).",
    "born again": "Except a man be born again, he cannot see the kingdom of God (John 3:3). Being born again, not of corruptible seed, but of incorruptible, by the word of God (1 Peter 1:23).",
    "bread of life": "I am the bread of life: he that cometh to me shall never hunger (John 6:35).",
    "bride of christ": "The marriage of the Lamb is come, and his wife hath made herself ready (Revelation 19:7).",
    "body of christ": "Ye are the body of Christ, and members in particular (1 Corinthians 12:27).",
    "book of life": "Whosoever was not found written in the book of life was cast into the lake of fire (Revelation 20:15).",
    "calling": "Walk worthy of the vocation wherewith ye are called (Ephesians 4:1). Whom he did predestinate, them he also called (Romans 8:30).",
    "calvary": "When they were come to the place, which is called Calvary, there they crucified him (Luke 23:33).",
    "charity": "Charity suffereth long, and is kind… Charity never faileth (1 Corinthians 13:4, 8).",
    "christ": "Thou art the Christ, the Son of the living God (Matthew 16:16). Christ died for our sins according to the scriptures (1 Corinthians 15:3).",
    "christian": "The disciples were called Christians first in Antioch (Acts 11:26).",
    "church": "Upon this rock I will build my church; and the gates of hell shall not prevail against it (Matthew 16:18).",
    "commandments": "If ye love me, keep my commandments (John 14:15). On these two commandments hang all the law and the prophets (Matthew 22:40).",
    "communion": "The cup of blessing which we bless, is it not the communion of the blood of Christ? (1 Corinthians 10:16).",
    "confession": "If we confess our sins, he is faithful and just to forgive us our sins (1 John 1:9).",
    "covenant": "This is my blood of the new testament, which is shed for many for the remission of sins (Matthew 26:28).",
    "creation": "In the beginning God created the heaven and the earth (Genesis 1:1). All things were made by him (John 1:3).",
    "cross": "God forbid that I should glory, save in the cross of our Lord Jesus Christ (Galatians 6:14).",
    "crucifixion": "They crucified him… and the scripture was fulfilled (Mark 15:25–28). He was wounded for our transgressions (Isaiah 53:5).",
    "comforter": "I will pray the Father, and he shall give you another Comforter (John 14:16).",
    "daniel": "Daniel purposed in his heart that he would not defile himself (Daniel 1:8). God is a revealer of secrets (Daniel 2:28).",
    "david": "I have found David the son of Jesse, a man after mine own heart (Acts 13:22).",
    "death": "The wages of sin is death; but the gift of God is eternal life through Jesus Christ our Lord (Romans 6:23).",
    "deliverance": "Who delivered us from so great a death, and doth deliver (2 Corinthians 1:10). He hath delivered us from the power of darkness (Colossians 1:13).",
    "demons": "Jesus rebuked the devil; and he departed out of him (Matthew 17:18). Resist the devil, and he will flee from you (James 4:7).",
    "discipleship": "If any man will come after me, let him deny himself, and take up his cross, and follow me (Matthew 16:24).",
    "doctrine": "Take heed unto thyself, and unto the doctrine; continue in them (1 Timothy 4:16).",
    "eden": "The Lord God planted a garden eastward in Eden (Genesis 2:8).",
    "election": "According as he hath chosen us in him before the foundation of the world (Ephesians 1:4).",
    "elijah": "Elijah was a man subject to like passions as we are, and he prayed earnestly (James 5:17).",
    "emmanuel": "They shall call his name Emmanuel, which being interpreted is, God with us (Matthew 1:23).",
    "end times": "This know also, that in the last days perilous times shall come (2 Timothy 3:1).",
    "eternal life": "And this is life eternal, that they might know thee the only true God, and Jesus Christ (John 17:3).",
    "evangelism": "Go ye into all the world, and preach the gospel to every creature (Mark 16:15).",
    "exodus": "I am the Lord thy God, which have brought thee out of the land of Egypt, out of the house of bondage (Exodus 20:2).",
    "faith": "Faith is the substance of things hoped for, the evidence of things not seen (Hebrews 11:1). Without faith it is impossible to please him (Hebrews 11:6).",
    "faithfulness": "Great is thy faithfulness (Lamentations 3:23). God is faithful (1 Corinthians 1:9).",
    "fall of man": "By one man sin entered into the world, and death by sin (Romans 5:12).",
    "father": "Our Father which art in heaven, Hallowed be thy name (Matthew 6:9).",
    "fasting": "When ye fast, be not, as the hypocrites, of a sad countenance (Matthew 6:16).",
    "fear of god": "The fear of the Lord is the beginning of wisdom (Proverbs 9:10).",
    "fellowship": "If we walk in the light… we have fellowship one with another (1 John 1:7).",
    "forgiveness": "Be ye kind one to another, tenderhearted, forgiving one another (Ephesians 4:32).",
    "free will": "Choose you this day whom ye will serve (Joshua 24:15). Whosoever will, let him take the water of life freely (Revelation 22:17).",
    "fruit of the spirit": "The fruit of the Spirit is love, joy, peace, longsuffering, gentleness, goodness, faith, meekness, temperance (Galatians 5:22–23).",
    "gospel": "I am not ashamed of the gospel of Christ: for it is the power of God unto salvation (Romans 1:16).",
    "grace": "By grace are ye saved through faith; and that not of yourselves: it is the gift of God (Ephesians 2:8).",
    "great commission": "Go ye therefore, and teach all nations… Teaching them to observe all things whatsoever I have commanded you (Matthew 28:19–20).",
    "god": "Hear, O Israel: The Lord our God is one Lord (Deuteronomy 6:4). God is a Spirit: and they that worship him must worship him in spirit and in truth (John 4:24).",
    "heaven": "In my Father’s house are many mansions… I go to prepare a place for you (John 14:2).",
    "hell": "Fear him which is able to destroy both soul and body in hell (Matthew 10:28).",
    "holy ghost": "Ye shall receive power, after that the Holy Ghost is come upon you (Acts 1:8).",
    "holy spirit": "The Spirit itself beareth witness with our spirit, that we are the children of God (Romans 8:16).",
    "holiness": "Be ye holy; for I am holy (1 Peter 1:16).",
    "hope": "Christ in you, the hope of glory (Colossians 1:27).",
    "humility": "Humble yourselves under the mighty hand of God, that he may exalt you in due time (1 Peter 5:6).",
    "healing": "I am the Lord that healeth thee (Exodus 15:26). By whose stripes ye were healed (1 Peter 2:24).",
    "israel": "I will be their God, and they shall be my people (Jeremiah 31:33).",
    "jesus": "Thou shalt call his name JESUS: for he shall save his people from their sins (Matthew 1:21).",
    "jesus christ": "Jesus Christ the same yesterday, and to day, and for ever (Hebrews 13:8).",
    "judgment": "It is appointed unto men once to die, but after this the judgment (Hebrews 9:27).",
    "justification": "Being justified by faith, we have peace with God through our Lord Jesus Christ (Romans 5:1).",
    "kingdom of god": "Seek ye first the kingdom of God, and his righteousness (Matthew 6:33).",
    "lamb of god": "Behold the Lamb of God, which taketh away the sin of the world (John 1:29).",
    "law": "The law was our schoolmaster to bring us unto Christ (Galatians 3:24).",
    "love": "God is love (1 John 4:8). Thou shalt love the Lord thy God… and thy neighbour as thyself (Matthew 22:37–39).",
    "messiah": "We have found the Messias, which is, being interpreted, the Christ (John 1:41).",
    "mercy": "His mercy endureth for ever (Psalm 136:1). Blessed are the merciful (Matthew 5:7).",
    "miracles": "Jesus of Nazareth, a man approved of God among you by miracles and wonders and signs (Acts 2:22).",
    "moses": "The Lord spake unto Moses face to face, as a man speaketh unto his friend (Exodus 33:11).",
    "new birth": "Except a man be born of water and of the Spirit, he cannot enter into the kingdom of God (John 3:5).",
    "new covenant": "This is the covenant that I will make with them after those days, saith the Lord (Hebrews 10:16).",
    "new jerusalem": "I John saw the holy city, new Jerusalem, coming down from God out of heaven (Revelation 21:2).",
    "obedience": "To obey is better than sacrifice (1 Samuel 15:22).",
    "passover": "Christ our passover is sacrificed for us (1 Corinthians 5:7).",
    "pentecost": "When the day of Pentecost was fully come… they were all filled with the Holy Ghost (Acts 2:1, 4).",
    "prayer": "Men ought always to pray, and not to faint (Luke 18:1). The effectual fervent prayer of a righteous man availeth much (James 5:16).",
    "praise": "Enter into his gates with thanksgiving, and into his courts with praise (Psalm 100:4).",
    "prophecy": "The testimony of Jesus is the spirit of prophecy (Revelation 19:10).",
    "propitiation": "He is the propitiation for our sins: and not for ours only, but also for the sins of the whole world (1 John 2:2).",
    "rapture": "The Lord himself shall descend from heaven… and the dead in Christ shall rise first: Then we which are alive… shall be caught up together with them in the clouds (1 Thessalonians 4:16–17).",
    "redemption": "In whom we have redemption through his blood, the forgiveness of sins (Ephesians 1:7).",
    "repentance": "Repent ye therefore, and be converted, that your sins may be blotted out (Acts 3:19).",
    "resurrection": "I am the resurrection, and the life (John 11:25). Now is Christ risen from the dead (1 Corinthians 15:20).",
    "revelation": "The Revelation of Jesus Christ, which God gave unto him (Revelation 1:1).",
    "righteousness": "The righteousness of God which is by faith of Jesus Christ unto all and upon all them that believe (Romans 3:22).",
    "sabbath": "Remember the sabbath day, to keep it holy (Exodus 20:8).",
    "sacrifice": "Present your bodies a living sacrifice, holy, acceptable unto God (Romans 12:1).",
    "salvation": "Neither is there salvation in any other: for there is none other name under heaven given among men, whereby we must be saved (Acts 4:12).",
    "sanctification": "This is the will of God, even your sanctification (1 Thessalonians 4:3).",
    "satan": "Your adversary the devil, as a roaring lion, walketh about, seeking whom he may devour (1 Peter 5:8).",
    "second coming": "This same Jesus… shall so come in like manner as ye have seen him go into heaven (Acts 1:11).",
    "sin": "All have sinned, and come short of the glory of God (Romans 3:23).",
    "son of god": "These are written, that ye might believe that Jesus is the Christ, the Son of God (John 20:31).",
    "son of man": "The Son of man is come to seek and to save that which was lost (Luke 19:10).",
    "spiritual gifts": "There are diversities of gifts, but the same Spirit (1 Corinthians 12:4).",
    "spiritual warfare": "Put on the whole armour of God, that ye may be able to stand against the wiles of the devil (Ephesians 6:11).",
    "temptation": "God is faithful, who will not suffer you to be tempted above that ye are able (1 Corinthians 10:13).",
    "tithes": "Bring ye all the tithes into the storehouse (Malachi 3:10).",
    "trinity": "Baptizing them in the name of the Father, and of the Son, and of the Holy Ghost (Matthew 28:19). The grace of the Lord Jesus Christ, and the love of God, and the communion of the Holy Ghost (2 Corinthians 13:14).",
    "truth": "Ye shall know the truth, and the truth shall make you free (John 8:32). I am the way, the truth, and the life (John 14:6).",
    "worship": "Thou shalt worship the Lord thy God, and him only shalt thou serve (Matthew 4:10).",
    "word of god": "The word of God is quick, and powerful, and sharper than any twoedged sword (Hebrews 4:12).",
    "zion": "Out of Zion, the perfection of beauty, God hath shined (Psalm 50:2).",
}

TOPIC_TEACHINGS.update(_TOPIC_EXTRA)

def normalize_query(q: str) -> str:
    return " ".join((q or "").lower().replace("-", " ").split())


def lead_hits(q: str, limit: int = 12) -> List[str]:
    qn = normalize_query(q)
    if not qn:
        return []
    hits: List[str] = []
    # Prefer longer phrases first
    ordered = sorted(LEAD_WORDS, key=lambda w: -len(w))
    for w in ordered:
        if w in qn:
            hits.append(w)
            if len(hits) >= limit:
                break
    return hits


def teachings_for_hits(hits: List[str]) -> List[Tuple[str, str]]:
    """Return (lead_word, teaching) pairs; fall back to related keys."""
    out: List[Tuple[str, str]] = []
    seen = set()
    for h in hits:
        key = h
        if key not in TOPIC_TEACHINGS:
            # try first word or known aliases
            for alt in (h, h.replace(" ", ""), h.split()[0] if h else ""):
                if alt in TOPIC_TEACHINGS:
                    key = alt
                    break
        if key in TOPIC_TEACHINGS and key not in seen:
            out.append((h, TOPIC_TEACHINGS[key]))
            seen.add(key)
        if len(out) >= 3:
            break
    return out


def chunk_paragraphs(text: str, max_chars: int = 420) -> List[str]:
    """Split into speakable paragraphs / thought chunks for pause-between-speech."""
    text = (text or "").strip()
    if not text:
        return []
    # Split on blank lines first, then sentences if too long
    raw_paras = [p.strip() for p in text.replace("\r", "").split("\n\n") if p.strip()]
    if not raw_paras:
        raw_paras = [text]
    chunks: List[str] = []
    for para in raw_paras:
        if len(para) <= max_chars:
            chunks.append(para)
            continue
        # sentence split
        buf = ""
        for part in para.replace(". ", ".\n").split("\n"):
            part = part.strip()
            if not part:
                continue
            if buf and len(buf) + 1 + len(part) > max_chars:
                chunks.append(buf.strip())
                buf = part
            else:
                buf = (buf + " " + part).strip()
        if buf:
            chunks.append(buf.strip())
    return chunks or [text]
