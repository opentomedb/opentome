-- =====================================================================
-- Multi-market manga / light-novel metadata catalogue
-- Schema v1 (2026-08-26)
--
-- Every design choice here traces to an empirical finding in docs/.
-- Comments cite which one, so nothing is cargo-culted.
-- =====================================================================

PRAGMA user_version = 1;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- IDENTIFIERS
--
-- These are a PUBLIC CONTRACT. Once Mangarr/Kavita/Komga store one, it
-- must resolve forever. The commercial moat is the IDs, not the bytes
-- (cf. IMDb/TheTVDB) -- so churn here breaks every consumer at once.
--
-- Rules, non-negotiable:
--   1. Opaque + prefixed ('w_', 'rl_', 'v_', 'ch_'). No meaning encoded,
--      so a corrected fact never forces a re-key.
--   2. NEVER reused, NEVER re-keyed. Merges write id_redirect; they do
--      not delete. (Lesson already learned the hard way in the GCD
--      migration: "do NOT big-bang re-key existing series".)
--   3. A retired id resolves via id_redirect forever -- never 404.
-- ---------------------------------------------------------------------

CREATE TABLE id_redirect (
    old_id      TEXT PRIMARY KEY,
    new_id      TEXT NOT NULL,
    entity      TEXT NOT NULL,          -- work | release_line | volume | chapter
    reason      TEXT,                   -- duplicate_merge | split | correction
    created_at  TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- WORK -- the canonical creative work, language- and medium-neutral.
-- Japanese origin is the spine; every market edition derives from it.
-- ---------------------------------------------------------------------

CREATE TABLE work (
    id            TEXT PRIMARY KEY,     -- 'w_<12hex>'
    primary_title TEXT NOT NULL,        -- best-known English/romaji title
    native_title  TEXT,                 -- original-script title
    year_started  INTEGER,
    demographic   TEXT,                 -- shounen | seinen | shoujo | josei | kodomo
    status        TEXT,                 -- ongoing | completed | hiatus | cancelled
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- Localized titles are a HARD PREREQUISITE, not enrichment.
-- Finding: the French edition is "L'attaque des titans"; searching the
-- English or Japanese title against BnF returns nothing usable.
CREATE TABLE work_title (
    work_id   TEXT NOT NULL REFERENCES work(id),
    language  TEXT NOT NULL,            -- ja | en | fr | de | es | it | pt
    title     TEXT NOT NULL,
    kind      TEXT NOT NULL,            -- official | romanized | alias | abbreviation
    PRIMARY KEY (work_id, language, title)
);
CREATE INDEX idx_work_title_title ON work_title(title COLLATE NOCASE);

-- Typed, directional edges between works.
-- Vocabulary deliberately mirrors AniList's: already battle-tested on
-- this domain, recognised by users, and gives free interop.
-- Finding: Re:Zero's manga arcs are not "spin-offs" -- they are separate
-- serialized ADAPTATIONS of arcs of one light novel. A boolean cannot
-- express that; a typed edge can.
CREATE TABLE work_relation (
    from_work_id TEXT NOT NULL REFERENCES work(id),
    to_work_id   TEXT NOT NULL REFERENCES work(id),
    kind         TEXT NOT NULL,         -- adaptation | prequel | sequel | side_story
                                        -- | alternative | spin_off | parent | summary
    sequence     INTEGER,               -- reading order within a franchise
    source_range TEXT,                  -- e.g. '[10,15]' = adapts LN vols 10-15
    PRIMARY KEY (from_work_id, to_work_id, kind)
);

-- ---------------------------------------------------------------------
-- RELEASE LINE -- one medium, one market, one publisher.
--
-- This is the level at which volume numbering is coherent. Merging lines
-- corrupts numbering: Re:Zero "Chapter 3" vol 1 and "Chapter 4" vol 1 are
-- both volume 1. Independence here is FORCED by the data, not chosen.
--
-- Finding: flattened franchise articles produced the only large errors in
-- cross-verification (SAO v6 was actually "Progressive 3 (light novel)").
--
-- `medium` is intentionally open-ended TEXT, not an enum: Solo Leveling in
-- the reference library is already manhwa, so a fixed manga/LN pair is
-- under-general on day one.
-- ---------------------------------------------------------------------

CREATE TABLE release_line (
    id          TEXT PRIMARY KEY,       -- 'rl_<12hex>'
    work_id     TEXT NOT NULL REFERENCES work(id),
    parent_id   TEXT,                   -- the line this arc was split from (release_lines.split_arcs)
    medium      TEXT NOT NULL,          -- manga | light_novel | manhwa | manhua
                                        -- | webtoon | novel | artbook | databook
    market      TEXT NOT NULL,          -- JP | US | GB | FR | DE | ES | IT | BR
    language    TEXT NOT NULL,
    publisher   TEXT,
    imprint     TEXT,
    format      TEXT,                   -- single | omnibus | deluxe | box_set | digital
    status      TEXT,                   -- ongoing | completed | stalled | cancelled
                                        -- 'stalled' is the highest-value unserved field:
                                        -- English editions die mid-run constantly and
                                        -- no existing tool reports it.
    volume_count INTEGER,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX idx_rl_work   ON release_line(work_id);
CREATE INDEX idx_rl_filter ON release_line(medium, market);

-- ---------------------------------------------------------------------
-- VOLUME
--
-- Dates carry THREE qualifiers, not one. Finding: 49 of 50 cross-source
-- disagreements were exact multiples of 7 days, 45 in the same direction
-- -- i.e. two sources answering different questions (publication date vs
-- retail on-sale date), not one being wrong. Storing a bare date silently
-- mixes them, which is precisely the quiet wrongness that killed Readarr.
--
-- page_count validation is per-FORMAT, not per-medium. Finding: LN median
-- 240pp vs manga ~185pp overlap far too much to discriminate, but German
-- omnibus editions run 450-472pp -- outside the legacy 80-400 window.
-- ---------------------------------------------------------------------

CREATE TABLE volume (
    id              TEXT PRIMARY KEY,   -- 'v_<12hex>'
    release_line_id TEXT NOT NULL REFERENCES release_line(id),
    number          TEXT NOT NULL,      -- TEXT: fractional/side volumes exist ('7.5')
    title           TEXT,
    isbn13          TEXT,
    isbn10          TEXT,
    page_count      INTEGER,
    format          TEXT,               -- single | omnibus | deluxe | box_set

    release_date            TEXT,       -- ISO-8601, truncated to its precision
    release_date_precision  TEXT,       -- day | month | year
    release_date_type       TEXT,       -- on_sale | published | digital | street
                                        -- | legal_deposit | unknown

    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (release_line_id, number)
);
CREATE INDEX idx_vol_isbn ON volume(isbn13);
CREATE INDEX idx_vol_rl   ON volume(release_line_id);

-- ---------------------------------------------------------------------
-- CHAPTER -- canonical serialized unit, owned by the WORK not the volume.
-- Mandatory, not optional: webtoons and digital-first series have no
-- volumes at all, so a volume-only catalogue is empty for the fastest-
-- growing category.
-- ---------------------------------------------------------------------

CREATE TABLE chapter (
    id          TEXT PRIMARY KEY,       -- 'ch_<12hex>'
    work_id     TEXT NOT NULL REFERENCES work(id),
    number      TEXT NOT NULL,          -- TEXT: '45.5' omake/extras are real
    title       TEXT,                   -- prefer the publisher's, never a fan translation
    magazine    TEXT,
    serialized_date TEXT,
    UNIQUE (work_id, number)
);

-- ---------------------------------------------------------------------
-- COMPOSITION -- THE unifying primitive.
--
-- One relation expresses three problems that looked separate:
--   * an omnibus contains volumes        [1,2,3]
--   * a French volume contains JP volumes [1,2]
--   * any volume contains chapters        [1..7]
-- The existing GCD-era `composition` JSON array generalised exactly.
-- ---------------------------------------------------------------------

CREATE TABLE composition (
    volume_id    TEXT NOT NULL REFERENCES volume(id),
    contains     TEXT NOT NULL,         -- chapter | volume
    ref_list     TEXT NOT NULL,         -- JSON array: '[1,2,3]' / '["1","2.5"]'
    ref_line_id  TEXT REFERENCES release_line(id),  -- for cross-market volume mapping
    PRIMARY KEY (volume_id, contains, ref_list)
);

-- ---------------------------------------------------------------------
-- CLAIM -- per-field provenance, and the calibration substrate.
--
-- Commercially critical: without per-field provenance you can never
-- retroactively emit a "clean view" filtered to unencumbered sources
-- (DNB is CC0; Google Books and MangaDex forbid database-building
-- entirely). That option is cheap now and unrecoverable later.
--
-- Stores CLAIMS, not just the winner, so cross-source disagreement is
-- preserved rather than discarded -- that disagreement IS the confidence
-- signal, and its shape (week-multiple offsets) is diagnostic.
-- ---------------------------------------------------------------------

CREATE TABLE claim (
    entity       TEXT NOT NULL,         -- work | release_line | volume | chapter
    entity_id    TEXT NOT NULL,
    field        TEXT NOT NULL,         -- e.g. 'release_date', 'page_count'
    value        TEXT NOT NULL,
    source       TEXT NOT NULL,         -- dnb | bnf | openbd | wikipedia | viz | ...
    source_url   TEXT,
    licence      TEXT NOT NULL,         -- cc0 | open | facts_only | restricted
                                        -- 'restricted' NEVER enters the clean view
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (entity, entity_id, field, source)
);
CREATE INDEX idx_claim_lookup  ON claim(entity, entity_id, field);
CREATE INDEX idx_claim_licence ON claim(licence);
-- Resume/incremental queries ask "does this entity already have a claim from
-- source X?". Without these that scan is O(claims) and an enrichment restart
-- hung past 120s on a 270k-row table. With them it is instant.
CREATE INDEX idx_claim_entity_source ON claim(entity_id, source);
CREATE INDEX idx_claim_source        ON claim(source);

-- Resolution outcome: which claim won, how sure we are, and why.
-- Consumers MUST be able to read confidence -- Mangarr should auto-accept
-- above a threshold and queue the rest, which is the direct fix for the
-- silent-wrong-match class of bug (25% of the reference library bound to
-- the wrong series before a match guard was added).
CREATE TABLE resolution (
    entity      TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    field       TEXT NOT NULL,
    value       TEXT NOT NULL,
    confidence  REAL NOT NULL,          -- 0.0 - 1.0
    basis       TEXT NOT NULL,          -- agreed | single_source | semantic_variance
                                        -- | escalated | manual_override
    n_agree     INTEGER,
    n_sources   INTEGER,
    notes       TEXT,
    PRIMARY KEY (entity, entity_id, field)
);

-- Manual pins beat every automated source. Direct descendant of
-- overrides.json -- the instant fix that doesn't wait for a release cycle.
CREATE TABLE override (
    entity     TEXT NOT NULL,
    entity_id  TEXT NOT NULL,
    field      TEXT NOT NULL,
    value      TEXT NOT NULL,
    reason     TEXT,
    author     TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (entity, entity_id, field)
);

-- ---------------------------------------------------------------------
-- External id cross-reference. Populate it -- the GCD-era schema declared
-- these columns and always wrote NULL, and ID reconciliation is usually a
-- metadata API's headline feature.
-- ---------------------------------------------------------------------

CREATE TABLE external_id (
    entity     TEXT NOT NULL,
    entity_id  TEXT NOT NULL,
    scheme     TEXT NOT NULL,           -- anilist | mangaupdates | mangadex
                                        -- | mal | wikidata | gcd | isbn
    value      TEXT NOT NULL,
    PRIMARY KEY (entity, entity_id, scheme, value)
);
CREATE INDEX idx_ext_lookup ON external_id(scheme, value);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------------------------------------------------------------------
-- The commercially clean view: only unencumbered provenance.
-- ---------------------------------------------------------------------
-- Commercially usable subset. 'noncommercial' is EXCLUDED: openBD is
-- purpose-limited to book promotion, and Open Library inherits Internet
-- Archive terms restricting use to noncommercial scholarship and research.
CREATE VIEW clean_claim AS
    SELECT * FROM claim WHERE licence IN ('cc0', 'open', 'facts_only');

-- Everything usable in a FREE, non-commercial release.
CREATE VIEW free_claim AS
    SELECT * FROM claim WHERE licence <> 'restricted';
