-- Shop database for catalog and checkout. Runs once on an empty data directory.
-- PostgreSQL is started with shared_preload_libraries=pg_stat_statements and track_io_timing=on.

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE ROLE shop_app LOGIN PASSWORD 'shop_app';
CREATE ROLE sre_ro LOGIN PASSWORD 'sre_ro';
CREATE ROLE sre_writer LOGIN PASSWORD 'sre_writer';
CREATE ROLE exporter LOGIN PASSWORD 'exporter';

GRANT pg_monitor TO sre_ro;
GRANT pg_monitor TO exporter;
GRANT pg_monitor TO sre_writer;
GRANT pg_signal_backend TO sre_writer;
GRANT shop_app TO sre_writer;

GRANT CONNECT ON DATABASE shop TO shop_app, sre_ro, sre_writer, exporter;
GRANT USAGE ON SCHEMA public TO shop_app, sre_ro, sre_writer, exporter;
GRANT CREATE ON SCHEMA public TO shop_app;
GRANT EXECUTE ON FUNCTION pg_stat_statements_reset(oid, oid, bigint) TO shop_app, sre_writer;

CREATE TABLE products (
  sku text PRIMARY KEY,
  name text NOT NULL,
  price numeric,
  stock integer NOT NULL DEFAULT 0,
  category text NOT NULL
);

CREATE TABLE orders (
  id bigserial PRIMARY KEY,
  sku text NOT NULL REFERENCES products (sku),
  qty integer NOT NULL,
  note text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO products (sku, name, price, stock, category) VALUES
  ('mug', 'Field mug', 18, 1000000, 'brew'),
  ('kettle', 'Pour kettle', 42, 1000000, 'brew'),
  ('null-row', 'Unpriced sample', NULL, 1, 'sample'),
  ('locked-sku', 'Lock target', 1, 1, 'internal');

INSERT INTO orders (sku, qty, note, created_at)
SELECT
  (ARRAY['mug', 'kettle', 'null-row'])[1 + (g % 3)],
  1 + (g % 4),
  'order note ' || g,
  now() - (g * interval '1 second')
FROM generate_series(1, 200000) AS g;

ALTER TABLE products OWNER TO shop_app;
ALTER TABLE orders OWNER TO shop_app;
ALTER SEQUENCE orders_id_seq OWNER TO shop_app;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO sre_ro, exporter;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO shop_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO shop_app;

SET ROLE shop_app;
CREATE INDEX orders_sku_created_idx ON orders (sku, created_at DESC);
RESET ROLE;

ANALYZE products;
ANALYZE orders;
