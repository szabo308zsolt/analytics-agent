import sqlite3


def init_sql_server():
    conn = sqlite3.connect("shop.db")
    conn.executescript("""
    CREATE TABLE  IF NOT EXISTS customers (id INTEGER PRIMARY KEY, name TEXT, country TEXT);
    CREATE TABLE  IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER REFERENCES customers(id),
        amount REAL,
        order_date TEXT
    );
    INSERT INTO customers VALUES (1,'Ana','SG'),(2,'Ben','MY'),(3,'Chloe','SG') ON CONFLICT DO NOTHING;
    INSERT INTO orders VALUES
    (1,1,120.0,'2026-09-01'),(2,1,80.0,'2026-09-15'),
    (3,2,200.0,'2026-10-02'),(4,3,50.0,'2026-10-10') ON CONFLICT DO NOTHING;
    """)
    sample_output = conn.execute("SELECT * FROM customers limit 2").fetchall()
    for line in sample_output:
        print(line)
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_sql_server()
    