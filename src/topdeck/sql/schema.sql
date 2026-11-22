-- TopDeck's graph: one table per kind of thing, one table per kind of link.
--
-- Run inside an empty schema with search_path set to it; graph.py does both.
-- Every link row carries its source (the Scryfall field it came from) and its method.
-- Every link here is 'given': read from a field, never guessed. Links extracted from
-- rules text arrive in a later phase with other methods.
--
-- Columns marked DERIVED are worked out from other rows after loading. They are not
-- read from any one Scryfall field, so they carry no source of their own.
--
-- Not loaded: loyalty, defense, colour indicator, produced mana, flavour text and the
-- artist of each face. The blueprint's graph doesn't need them yet.

-- ---------------------------------------------------------------- things

CREATE TABLE colours (
    code text PRIMARY KEY,           -- W, U, B, R, G
    name text NOT NULL UNIQUE
);

CREATE TABLE types      (name text PRIMARY KEY);   -- Creature, Instant, Land ...
CREATE TABLE subtypes   (name text PRIMARY KEY);   -- Goblin, Elf, Aura ...
CREATE TABLE supertypes (name text PRIMARY KEY);   -- Legendary, Basic, Snow ...
CREATE TABLE keywords   (name text PRIMARY KEY);   -- Flying, Trample ...
CREATE TABLE formats    (name text PRIMARY KEY);   -- vintage, modern, pauper ...

CREATE TABLE cards (
    card_id      uuid PRIMARY KEY,   -- Scryfall's oracle_id: one per unique card
    name         text NOT NULL,
    layout       text NOT NULL,
    mana_cost    text NOT NULL,
    mana_value   numeric NOT NULL,
    rules_text   text NOT NULL,
    power        text,               -- text, because some cards have a power of '*'
    power_number integer,            -- the power when it is a whole number, else NULL
    toughness    text,
    first_printed date               -- DERIVED: the date of its earliest real printing
);

-- A face of a card that has more than one. The card itself is its front face,
-- except a split card, which is both halves; each face keeps its own facts here.
CREATE TABLE faces (
    card_id    uuid NOT NULL REFERENCES cards,
    position   smallint NOT NULL,    -- 0 is the front
    name       text NOT NULL,
    mana_cost  text NOT NULL,
    rules_text text NOT NULL,
    power      text,
    toughness  text,
    PRIMARY KEY (card_id, position)
);

CREATE TABLE sets (
    code              text PRIMARY KEY,
    name              text NOT NULL,
    set_type          text NOT NULL,
    earliest_printing date NOT NULL  -- DERIVED: the earliest real printing in the graph from
                                     -- this set; not Scryfall's release date for the set
);

CREATE TABLE artists (
    artist_id integer PRIMARY KEY,
    name      text NOT NULL UNIQUE   -- as credited on the card
);

-- One real printing of a card: on paper, in an ordinary set. Its two links, to its card
-- and to its set, are columns here, and each has a source of its own.
CREATE TABLE printings (
    printing_id      uuid PRIMARY KEY,   -- Scryfall's id for this printing
    card_id          uuid NOT NULL REFERENCES cards,
    card_source      text NOT NULL,      -- where card_id was read from
    set_code         text NOT NULL REFERENCES sets,
    set_source       text NOT NULL,      -- where set_code was read from
    collector_number text NOT NULL,
    rarity           text NOT NULL,
    released_at      date NOT NULL,
    method           text NOT NULL
);

-- ---------------------------------------------------------------- links from a card

CREATE TABLE card_colour (
    card_id uuid NOT NULL REFERENCES cards,
    colour  text NOT NULL REFERENCES colours,
    source  text NOT NULL,
    method  text NOT NULL,
    PRIMARY KEY (card_id, colour)
);

CREATE TABLE card_colour_identity (
    card_id uuid NOT NULL REFERENCES cards,
    colour  text NOT NULL REFERENCES colours,
    source  text NOT NULL,
    method  text NOT NULL,
    PRIMARY KEY (card_id, colour)
);

CREATE TABLE card_type (
    card_id uuid NOT NULL REFERENCES cards,
    type    text NOT NULL REFERENCES types,
    source  text NOT NULL,
    method  text NOT NULL,
    PRIMARY KEY (card_id, type)
);

CREATE TABLE card_subtype (
    card_id uuid NOT NULL REFERENCES cards,
    subtype text NOT NULL REFERENCES subtypes,
    source  text NOT NULL,
    method  text NOT NULL,
    PRIMARY KEY (card_id, subtype)
);

CREATE TABLE card_supertype (
    card_id   uuid NOT NULL REFERENCES cards,
    supertype text NOT NULL REFERENCES supertypes,
    source    text NOT NULL,
    method    text NOT NULL,
    PRIMARY KEY (card_id, supertype)
);

-- Scryfall gives keywords for the whole card, not for each face, so a keyword that only
-- the back face has is still a link from the card. Its source says so.
CREATE TABLE card_keyword (
    card_id uuid NOT NULL REFERENCES cards,
    keyword text NOT NULL REFERENCES keywords,
    source  text NOT NULL,
    method  text NOT NULL,
    PRIMARY KEY (card_id, keyword)
);

-- Only 'legal', 'restricted' and 'banned' are stored. A card with no row for a format
-- is not legal there.
CREATE TABLE card_legality (
    card_id uuid NOT NULL REFERENCES cards,
    format  text NOT NULL REFERENCES formats,
    status  text NOT NULL CHECK (status IN ('legal', 'restricted', 'banned')),
    source  text NOT NULL,
    method  text NOT NULL,
    PRIMARY KEY (card_id, format)
);

-- ---------------------------------------------------------------- links from a face

CREATE TABLE face_colour (
    card_id  uuid NOT NULL,
    position smallint NOT NULL,
    colour   text NOT NULL REFERENCES colours,
    source   text NOT NULL,
    method   text NOT NULL,
    PRIMARY KEY (card_id, position, colour),
    FOREIGN KEY (card_id, position) REFERENCES faces
);

CREATE TABLE face_type (
    card_id  uuid NOT NULL,
    position smallint NOT NULL,
    type     text NOT NULL REFERENCES types,
    source   text NOT NULL,
    method   text NOT NULL,
    PRIMARY KEY (card_id, position, type),
    FOREIGN KEY (card_id, position) REFERENCES faces
);

CREATE TABLE face_subtype (
    card_id  uuid NOT NULL,
    position smallint NOT NULL,
    subtype  text NOT NULL REFERENCES subtypes,
    source   text NOT NULL,
    method   text NOT NULL,
    PRIMARY KEY (card_id, position, subtype),
    FOREIGN KEY (card_id, position) REFERENCES faces
);

CREATE TABLE face_supertype (
    card_id   uuid NOT NULL,
    position  smallint NOT NULL,
    supertype text NOT NULL REFERENCES supertypes,
    source    text NOT NULL,
    method    text NOT NULL,
    PRIMARY KEY (card_id, position, supertype),
    FOREIGN KEY (card_id, position) REFERENCES faces
);

-- ---------------------------------------------------------------- links from a printing

CREATE TABLE printing_artist (
    printing_id uuid NOT NULL REFERENCES printings,
    artist_id   integer NOT NULL REFERENCES artists,
    source      text NOT NULL,
    method      text NOT NULL,
    PRIMARY KEY (printing_id, artist_id)
);

-- ---------------------------------------------------------------- indexes
-- Each link table's key starts with the card, so finding a card's links is fast.
-- These make the other direction fast too: every Goblin, every red card.

CREATE INDEX card_colour_by_colour       ON card_colour (colour);
CREATE INDEX card_identity_by_colour     ON card_colour_identity (colour);
CREATE INDEX card_type_by_type           ON card_type (type);
CREATE INDEX card_subtype_by_subtype     ON card_subtype (subtype);
CREATE INDEX card_supertype_by_supertype ON card_supertype (supertype);
CREATE INDEX card_keyword_by_keyword     ON card_keyword (keyword);
CREATE INDEX card_legality_by_format     ON card_legality (format, status);
CREATE INDEX printings_by_card           ON printings (card_id);
CREATE INDEX printings_by_set            ON printings (set_code);
CREATE INDEX printing_artist_by_artist   ON printing_artist (artist_id);
CREATE INDEX cards_by_name               ON cards (name);
