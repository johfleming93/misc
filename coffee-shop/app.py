import sqlite3
from flask import Flask, g, jsonify, request, render_template, abort
from collections import Counter
import os
import threading
import time
import logging

# Configuration
DATABASE = os.path.join(os.path.dirname(__file__), 'coffee.db')
# Interval (seconds) between automatic DB updates (default: 24 hours)
BACKGROUND_UPDATE_INTERVAL = int(os.getenv('DB_UPDATE_INTERVAL', 60 * 60 * 24))

app = Flask(__name__, template_folder='templates', static_folder='static')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_db():
    """Return a sqlite3 connection unique to the request context (stored in flask.g)."""
    db = getattr(g, '_database', None)
    if db is None:
        # check_same_thread=False to allow using the connection safely if a background thread
        # touches the DB while the app is running. We still prefer to use app.app_context()
        # for background tasks to get their own connection context.
        db = g._database = sqlite3.connect(DATABASE, check_same_thread=False)
        db.row_factory = sqlite3.Row
    return db


def init_db():
    """
    Ensure the database schema and seed data are present.
    Safe to call repeatedly.
    """
    logger.info("Running init_db to ensure schema & seed data.")
    db = get_db()
    cursor = db.cursor()
    cursor.executescript('''
    CREATE TABLE IF NOT EXISTS menu_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        inventory INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT,
        items TEXT,
        total REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    ''')
    db.commit()

    # ensure `inventory` column exists for older DBs
    cols = [r['name'] for r in db.execute("PRAGMA table_info(menu_items)").fetchall()]
    if 'inventory' not in cols:
        logger.info("Adding missing 'inventory' column to menu_items.")
        db.execute('ALTER TABLE menu_items ADD COLUMN inventory INTEGER DEFAULT 0')
        db.commit()

    cur = db.execute('SELECT COUNT(*) as c FROM menu_items')
    if cur.fetchone()['c'] == 0:
        items = [
            ('Espresso', 2.5, 20),
            ('Latte', 3.5, 15),
            ('Cappuccino', 3.0, 15),
            ('Tea', 2.0, 25),
        ]
        logger.info("Seeding default menu items.")
        db.executemany('INSERT INTO menu_items (name, price, inventory) VALUES (?, ?, ?)', items)
        db.commit()


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


@app.route('/')
def index():
    # Ensure DB exists/seeded before serving the UI
    init_db()
    return render_template('index.html')


@app.route('/api/menu', methods=['GET', 'POST'])
def api_menu():
    db = get_db()
    if request.method == 'GET':
        rows = db.execute('SELECT id, name, price, inventory FROM menu_items').fetchall()
        return jsonify([dict(r) for r in rows])
    else:
        data = request.get_json() or {}
        name = data.get('name')
        try:
            price = float(data.get('price', 0))
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid price'}), 400
        try:
            inventory = int(data.get('inventory', 0))
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid inventory'}), 400
        if not name:
            return jsonify({'error': 'name required'}), 400
        cur = db.execute('INSERT INTO menu_items (name, price, inventory) VALUES (?, ?, ?)', (name, price, inventory))
        db.commit()
        item_id = cur.lastrowid
        row = db.execute('SELECT id, name, price, inventory FROM menu_items WHERE id=?', (item_id,)).fetchone()
        return jsonify(dict(row)), 201


@app.route('/api/menu/<int:item_id>', methods=['PUT', 'DELETE'])
def api_menu_item(item_id):
    db = get_db()
    if request.method == 'PUT':
        data = request.get_json() or {}
        name = data.get('name')
        try:
            price = data.get('price')
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid price'}), 400
        try:
            inventory = data.get('inventory')
            inventory = int(inventory) if inventory is not None else None
        except (TypeError, ValueError):
            return jsonify({'error': 'invalid inventory'}), 400

        # build update
        parts = []
        params = []
        if name is not None:
            parts.append('name = ?')
            params.append(name)
        if price is not None:
            parts.append('price = ?')
            params.append(price)
        if inventory is not None:
            parts.append('inventory = ?')
            params.append(inventory)
        if not parts:
            return jsonify({'error': 'no fields to update'}), 400
        params.append(item_id)
        db.execute(f"UPDATE menu_items SET {', '.join(parts)} WHERE id = ?", params)
        db.commit()
        row = db.execute('SELECT id, name, price, inventory FROM menu_items WHERE id=?', (item_id,)).fetchone()
        if not row:
            return jsonify({'error': 'not found'}), 404
        return jsonify(dict(row))
    else:
        cur = db.execute('SELECT id FROM menu_items WHERE id=?', (item_id,)).fetchone()
        if not cur:
            return jsonify({'error': 'not found'}), 404
        db.execute('DELETE FROM menu_items WHERE id=?', (item_id,))
        db.commit()
        return jsonify({'status': 'deleted'})


@app.route('/api/orders', methods=['GET', 'POST'])
def api_orders():
    db = get_db()
    if request.method == 'POST':
        data = request.get_json() or {}
        name = data.get('customer_name', 'Guest')
        items = data.get('items', [])
        if not isinstance(items, list):
            return jsonify({'error': 'items must be a list of menu item ids'}), 400
        if not items:
            total = 0.0
            db.execute('INSERT INTO orders (customer_name, items, total) VALUES (?, ?, ?)', (name, '', total))
            db.commit()
            return jsonify({'status': 'ok', 'total': total}), 201

        # Normalize item ids to ints and validate
        try:
            items = [int(i) for i in items]
        except (TypeError, ValueError):
            return jsonify({'error': 'items must be a list of integers (menu item ids)'}), 400

        counts = Counter(items)
        keys = list(counts.keys())
        placeholders = ','.join('?' * len(keys))
        cur = db.execute(f'SELECT id, name, price, inventory FROM menu_items WHERE id IN ({placeholders})', keys)
        rows = cur.fetchall()
        prices = {row['id']: row['price'] for row in rows}
        inventory = {row['id']: row['inventory'] for row in rows}
        names = {row['id']: row['name'] for row in rows}

        insufficient = []
        for item_id, qty in counts.items():
            inv = inventory.get(item_id)
            if inv is None:
                insufficient.append(f'Item id {item_id} not found')
            elif inv < qty:
                insufficient.append(f"{names.get(item_id,'Item')} (id {item_id}) only {inv} left")
        if insufficient:
            return jsonify({'error': 'insufficient_inventory', 'details': insufficient}), 400

        total = 0.0
        for item_id, qty in counts.items():
            total += prices.get(item_id, 0) * qty
            db.execute('UPDATE menu_items SET inventory = inventory - ? WHERE id = ?', (qty, item_id))

        db.execute('INSERT INTO orders (customer_name, items, total) VALUES (?, ?, ?)', (name, ','.join(map(str, items)), total))
        db.commit()
        return jsonify({'status': 'ok', 'total': total}), 201
    else:
        rows = db.execute('SELECT id, customer_name, items, total, created_at FROM orders ORDER BY created_at DESC').fetchall()
        return jsonify([dict(r) for r in rows])


# Inventory alert endpoint
@app.route('/api/inventory-alert', methods=['GET'])
def inventory_alert():
    db = get_db()
    threshold_str = request.args.get('threshold', '5')
    try:
        threshold = int(threshold_str)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid threshold'}), 400
    rows = db.execute('SELECT id, name, inventory FROM menu_items WHERE inventory <= ?', (threshold,)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/update-db', methods=['POST'])
def trigger_update_db():
    """Manual endpoint to trigger DB init/seed. Useful for webhooks or admin actions."""
    try:
        with app.app_context():
            init_db()
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logger.exception("Error running manual DB update")
        return jsonify({'error': str(e)}), 500


def _periodic_db_updater(interval_seconds):
    """Background thread job that runs init_db() every interval_seconds with app context."""
    logger.info("Started periodic DB updater thread (interval=%s seconds).", interval_seconds)
    while True:
        try:
            with app.app_context():
                init_db()
        except Exception:
            logger.exception("Periodic DB updater failed")
        time.sleep(interval_seconds)


def start_periodic_db_updates(interval_seconds=BACKGROUND_UPDATE_INTERVAL):
    """
    Start a daemon thread to periodically call init_db.
    This function should only be called once (typically on startup).
    """
    thread = threading.Thread(target=_periodic_db_updater, args=(interval_seconds,))
    thread.daemon = True
    thread.start()
    return thread


if __name__ == '__main__':
    # Initialize DB now
    with app.app_context():
        init_db()
    if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
        start_periodic_db_updates()

    # Run server
    app.run(debug=True, port=5000)
