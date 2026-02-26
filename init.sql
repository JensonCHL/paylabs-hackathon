-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table 1: merchants
CREATE TABLE merchants (
    merchant_id TEXT PRIMARY KEY,
    business_name VARCHAR(255) NOT NULL,
    industry_type VARCHAR(100),
    join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    operating_city VARCHAR(100)
);

-- Table 2: transactions
CREATE TABLE transactions (
    transaction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    merchant_id TEXT REFERENCES merchants(merchant_id) ON DELETE CASCADE,
    gross_amount DECIMAL(15, 2) NOT NULL,
    net_amount DECIMAL(15, 2) NOT NULL,
    fee_deducted DECIMAL(15, 2) NOT NULL,
    status VARCHAR(50) NOT NULL, -- SUCCESS, PENDING, FAILED, REFUNDED
    payment_method VARCHAR(50) NOT NULL, -- QRIS, VA_BCA, E_WALLET_OVO, etc.
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 3: transaction_items
CREATE TABLE transaction_items (
    item_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id UUID REFERENCES transactions(transaction_id) ON DELETE CASCADE,
    item_name VARCHAR(255) NOT NULL,
    category VARCHAR(100),
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(15, 2) NOT NULL,
    UNIQUE (transaction_id, item_name)
);

-- Table 4: chat_logs
CREATE TABLE chat_logs (
    log_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chat_id UUID NOT NULL,
    merchant_id TEXT REFERENCES merchants(merchant_id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table 5: report_generation_staging
-- (This serves as the template for both staging and history as per the docs)
CREATE TABLE report_generation_staging (
    report_id TEXT PRIMARY KEY,
    merchant_id TEXT,
    generation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) NOT NULL DEFAULT 'PROCESSING', -- PROCESSING, READY, FAILED
    total_revenue DECIMAL(15, 2),
    transaction_count INTEGER,
    top_selling_item_name VARCHAR(255),
    top_selling_item_qty INTEGER,
    financial_summary TEXT,
    pattern_analysis TEXT,
    strategic_advice TEXT
);

-- Table 6: report_history
CREATE TABLE report_history (
    report_id TEXT PRIMARY KEY,
    merchant_id TEXT,
    generation_date TIMESTAMP,
    status VARCHAR(50),
    total_revenue DECIMAL(15, 2),
    transaction_count INTEGER,
    top_selling_item_name VARCHAR(255),
    top_selling_item_qty INTEGER,
    financial_summary TEXT,
    pattern_analysis TEXT,
    strategic_advice TEXT
);

-- MCP database roles
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mcp_read') THEN
        CREATE ROLE mcp_read LOGIN PASSWORD 'mcp_read';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mcp_write') THEN
        CREATE ROLE mcp_write LOGIN PASSWORD 'mcp_write';
    END IF;
END $$;

GRANT CONNECT ON DATABASE paylabs_db TO mcp_read, mcp_write;
GRANT USAGE ON SCHEMA public TO mcp_read, mcp_write;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_read;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mcp_read;

GRANT SELECT ON merchants, transactions, transaction_items, report_generation_staging TO mcp_write;
GRANT UPDATE ON report_generation_staging TO mcp_write;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO mcp_write;

-- Seed data (Jan 1, 2026 - Feb 28, 2026)
-- Note: 2026 is not a leap year, so February has 28 days.
SELECT setseed(0.42);

INSERT INTO merchants (merchant_id, business_name, industry_type, join_date, operating_city)
VALUES
    ('01', 'Warung SerbaAda', 'Retail', '2025-12-15', 'Jakarta');

WITH date_series AS (
    SELECT d::date AS day
    FROM generate_series('2026-01-01'::date, '2026-02-28'::date, interval '1 day') d
),
txn_counts AS (
    SELECT
        day,
        CASE
            WHEN day = '2026-01-01'::date THEN (floor(random() * 3) + 5)::int
            WHEN day BETWEEN '2026-02-11'::date AND '2026-02-17'::date THEN (floor(random() * 3) + 5)::int
            WHEN day = '2026-02-14'::date THEN (floor(random() * 3) + 5)::int
            ELSE (floor(random() * 2) + 1)::int
        END AS n
    FROM date_series
),
base_txn AS (
    SELECT
        uuid_generate_v4() AS transaction_id,
        '01' AS merchant_id,
        (floor(random() * 180000) + 20000)::numeric(15, 2) AS gross_amount,
        NULL::numeric(15, 2) AS net_amount,
        NULL::numeric(15, 2) AS fee_deducted,
        'SUCCESS' AS status,
        (ARRAY['QRIS','VA_BCA','E_WALLET_OVO','E_WALLET_DANA','CARD'])[floor(random() * 5) + 1] AS payment_method,
        (day + (random() * '23:59:59'::interval))::timestamp AS created_at
    FROM txn_counts
    JOIN LATERAL generate_series(1, n) g(i) ON true
)
INSERT INTO transactions (transaction_id, merchant_id, gross_amount, net_amount, fee_deducted, status, payment_method, created_at)
SELECT
    transaction_id,
    merchant_id,
    gross_amount,
    (gross_amount - fee)::numeric(15, 2) AS net_amount,
    fee::numeric(15, 2) AS fee_deducted,
    status,
    payment_method,
    created_at
FROM (
    SELECT
        *,
        (gross_amount * ((floor(random() * 9) + 7)::numeric / 1000)) AS fee
    FROM base_txn
) t;

WITH normal_items AS (
    SELECT *
    FROM (VALUES
        ('Beras 5kg', 'Grocery', 65000::numeric(15, 2)),
        ('Gula 1kg', 'Grocery', 18000::numeric(15, 2)),
        ('Minyak Goreng 1L', 'Grocery', 22000::numeric(15, 2)),
        ('Telur Ayam 1kg', 'Grocery', 30000::numeric(15, 2)),
        ('Mi Instan', 'Grocery', 3500::numeric(15, 2)),
        ('Jeruk 1kg', 'Fruit', 28000::numeric(15, 2)),
        ('Apel 1kg', 'Fruit', 32000::numeric(15, 2)),
        ('Pisang 1 sisir', 'Fruit', 25000::numeric(15, 2)),
        ('Kopi Sachet', 'Beverage', 2500::numeric(15, 2)),
        ('Teh Botol', 'Beverage', 6000::numeric(15, 2)),
        ('Roti Tawar', 'Snack', 15000::numeric(15, 2)),
        ('Biskuit', 'Snack', 12000::numeric(15, 2)),
        ('Cokelat Bar', 'Snack', 15000::numeric(15, 2)),
        ('Susu UHT 1L', 'Dairy', 20000::numeric(15, 2)),
        ('Sabun Mandi', 'Household', 8000::numeric(15, 2)),
        ('Shampoo Sachet', 'Household', 2000::numeric(15, 2)),
        ('Deterjen 1kg', 'Household', 30000::numeric(15, 2)),
        ('Pulsa 20k', 'Digital', 20000::numeric(15, 2)),
        ('Masker 3pcs', 'Health', 10000::numeric(15, 2))
    ) v(item_name, category, unit_price)
),
cny_items AS (
    SELECT *
    FROM (VALUES
        ('Jeruk Mandarin 1kg', 'CNY', 38000::numeric(15, 2)),
        ('Kue Keranjang', 'CNY', 45000::numeric(15, 2)),
        ('Hampers Imlek', 'CNY', 120000::numeric(15, 2)),
        ('Angpao (pak)', 'CNY', 15000::numeric(15, 2)),
        ('Kacang & Kuaci', 'CNY', 20000::numeric(15, 2)),
        ('Hiasan Lampion', 'CNY', 30000::numeric(15, 2))
    ) v(item_name, category, unit_price)
),
tx AS (
    SELECT transaction_id, created_at
    FROM transactions
    WHERE merchant_id = '01'
      AND created_at >= '2026-01-01'::date
      AND created_at < '2026-03-01'::date
),
pool AS (
    SELECT
        item_name,
        category,
        unit_price,
        CASE
            WHEN category = 'CNY' THEN 3.0
            ELSE 1.0
        END AS weight
    FROM (
        SELECT * FROM normal_items
        UNION ALL
        SELECT * FROM cny_items
    ) all_items
),
chosen_items AS (
    SELECT
        s.transaction_id,
        s.items_per_txn,
        p.item_name,
        p.category,
        p.unit_price,
        ROW_NUMBER() OVER (
            PARTITION BY s.transaction_id
            ORDER BY (random() * p.weight) DESC
        ) AS rn
    FROM (
        SELECT
            tx.transaction_id,
            tx.created_at,
            (floor(random() * 4) + 1)::int AS items_per_txn
        FROM tx
    ) s
    JOIN pool p
      ON (
            s.created_at::date BETWEEN '2026-02-11'::date AND '2026-02-17'::date
            OR p.category <> 'CNY'
         )
)
INSERT INTO transaction_items (transaction_id, item_name, category, quantity, unit_price)
SELECT
    c.transaction_id,
    c.item_name,
    c.category,
    (floor(random() * 3) + 1)::int AS quantity,
    c.unit_price
FROM chosen_items c
WHERE c.rn <= c.items_per_txn;
