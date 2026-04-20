-- ============================================================
-- Sample database: e-commerce analytics dataset
-- ============================================================

-- Create read-only role (used exclusively by the agent)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'readonly_user') THEN
        CREATE ROLE readonly_user LOGIN PASSWORD 'readonly_pass';
    END IF;
END
$$;

-- ============================================================
-- Schema
-- ============================================================

CREATE TABLE IF NOT EXISTS customers (
    customer_id   SERIAL PRIMARY KEY,
    name          VARCHAR(120) NOT NULL,
    email         VARCHAR(200) UNIQUE NOT NULL,
    country       VARCHAR(80)  NOT NULL,
    signup_date   DATE         NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id    SERIAL PRIMARY KEY,
    name          VARCHAR(200) NOT NULL,
    category      VARCHAR(80)  NOT NULL,
    unit_price    NUMERIC(10, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id      SERIAL PRIMARY KEY,
    customer_id   INTEGER REFERENCES customers(customer_id),
    order_date    DATE    NOT NULL,
    status        VARCHAR(30) NOT NULL CHECK (status IN ('completed','pending','cancelled','refunded'))
);

CREATE TABLE IF NOT EXISTS order_items (
    item_id       SERIAL PRIMARY KEY,
    order_id      INTEGER REFERENCES orders(order_id),
    product_id    INTEGER REFERENCES products(product_id),
    quantity      INTEGER NOT NULL CHECK (quantity > 0),
    unit_price    NUMERIC(10, 2) NOT NULL
);

-- ============================================================
-- Seed data
-- ============================================================

INSERT INTO customers (name, email, country, signup_date) VALUES
    ('Alice Johnson',  'alice@example.com',  'USA',     '2022-01-15'),
    ('Bob Smith',      'bob@example.com',    'UK',      '2022-03-22'),
    ('Carlos Rivera',  'carlos@example.com', 'Mexico',  '2022-06-10'),
    ('Diana Chen',     'diana@example.com',  'China',   '2022-08-05'),
    ('Eva Müller',     'eva@example.com',    'Germany', '2023-01-20'),
    ('Frank Osei',     'frank@example.com',  'Ghana',   '2023-03-14'),
    ('Grace Kim',      'grace@example.com',  'South Korea', '2023-05-30'),
    ('Hiro Tanaka',    'hiro@example.com',   'Japan',   '2023-07-18'),
    ('Isla Brown',     'isla@example.com',   'Australia', '2023-09-02'),
    ('Juan Lopez',     'juan@example.com',   'Spain',   '2024-01-11')
ON CONFLICT DO NOTHING;

INSERT INTO products (name, category, unit_price) VALUES
    ('Wireless Headphones',  'Electronics',  79.99),
    ('Running Shoes',        'Footwear',     59.99),
    ('Coffee Maker',         'Appliances',   49.99),
    ('Python Programming Book', 'Books',     39.99),
    ('Yoga Mat',             'Sports',       29.99),
    ('Smartwatch',           'Electronics', 199.99),
    ('Desk Lamp',            'Home Office',  34.99),
    ('Protein Powder',       'Health',       54.99),
    ('Noise Cancelling Earbuds', 'Electronics', 129.99),
    ('Standing Desk',        'Home Office',  349.99)
ON CONFLICT DO NOTHING;

INSERT INTO orders (customer_id, order_date, status) VALUES
    (1, '2023-02-10', 'completed'),
    (1, '2023-06-15', 'completed'),
    (2, '2023-03-20', 'completed'),
    (3, '2023-04-05', 'cancelled'),
    (4, '2023-05-12', 'completed'),
    (5, '2023-07-08', 'pending'),
    (6, '2023-08-22', 'completed'),
    (7, '2023-09-14', 'completed'),
    (8, '2023-10-01', 'refunded'),
    (9, '2023-11-18', 'completed'),
    (10,'2024-01-25', 'completed'),
    (1, '2024-02-14', 'completed'),
    (2, '2024-03-03', 'pending'),
    (4, '2024-03-20', 'completed'),
    (5, '2024-04-10', 'completed')
ON CONFLICT DO NOTHING;

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
    (1,  1, 1, 79.99),
    (1,  3, 2, 49.99),
    (2,  6, 1, 199.99),
    (3,  2, 1, 59.99),
    (3,  5, 1, 29.99),
    (4,  4, 3, 39.99),
    (5,  9, 1, 129.99),
    (6,  7, 2, 34.99),
    (7,  8, 1, 54.99),
    (8,  1, 1, 79.99),
    (9,  10,1, 349.99),
    (10, 6, 1, 199.99),
    (11, 2, 2, 59.99),
    (12, 3, 1, 49.99),
    (13, 9, 1, 129.99),
    (14, 1, 1, 79.99),
    (14, 7, 1, 34.99),
    (15, 5, 2, 29.99)
ON CONFLICT DO NOTHING;

-- ============================================================
-- Grant read-only access (enforcement at DB level)
-- ============================================================

GRANT CONNECT ON DATABASE analyst_db TO readonly_user;
GRANT USAGE ON SCHEMA public TO readonly_user;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readonly_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readonly_user;
