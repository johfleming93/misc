Coffee Shop — Minimal management tool

This is a tiny Flask + SQLite demo to manage a coffee shop menu and orders.

Quick start (Windows):

1. Create and activate a venv:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1    # or Activate.bat for cmd
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Run:

```powershell
python app.py
```

4. Open http://127.0.0.1:5000 in your browser.

Notes:
- The app uses an SQLite DB file `coffee.db` created next to `app.py`.
- This is intentionally small; extend it with authentication, inventory, or receipts as needed.
 - The app now supports editing menu item prices and inventory from the web UI (Manage Menu).
 - Menu items have an `inventory` integer; orders do not yet decrement inventory automatically.
 - Menu items have an `inventory` integer; orders now decrement inventory automatically when placed.
 - The web UI disables selection for items that are out of stock and will return an error if you try to order unavailable quantities.
Have fun using this.