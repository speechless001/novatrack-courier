from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import random

app = Flask(__name__)
app.secret_key = "novatrack_secret_key"

def create_tables():
    conn = get_db_connection()

    conn.execute("""
    CREATE TABLE IF NOT EXISTS packages (
        tracking_number TEXT PRIMARY KEY,
        customer TEXT,
        origin TEXT,
        destination TEXT,
        status TEXT
    )
    """)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS tracking_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tracking_number TEXT,
        update_message TEXT,
        update_time TEXT
    )
    """)

    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

import random
import string

def generate_tracking_number():
    conn = get_db_connection()

    while True:
        # mix of letters + numbers
        part1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        part2 = random.randint(1000, 9999)
        part3 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

        tracking_number = f"NVT-US-{part1}-{part2}-{part3}"

        existing = conn.execute(
            "SELECT * FROM packages WHERE tracking_number = ?",
            (tracking_number,)
        ).fetchone()

        if not existing:
            conn.close()
            return tracking_number
        
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/track", methods=["POST"])
def track_package():
    tracking_number = request.form["tracking_number"].strip().upper()

    conn = get_db_connection()

    package = conn.execute(
        "SELECT * FROM packages WHERE tracking_number = ?",
        (tracking_number,)
    ).fetchone()

    history = conn.execute(
        "SELECT * FROM tracking_history WHERE tracking_number = ? ORDER BY id ASC",
        (tracking_number,)
    ).fetchall()

    conn.close()

    return render_template(
        "result.html",
        tracking_number=tracking_number,
        package=package,
        history=history
    )

@app.route("/novatrack-admin")
def admin():

    if not session.get("admin_logged_in"):
        return redirect(url_for("login_page"))
    
    return render_template("admin.html")

@app.route("/create-shipment", methods=["POST"])
def create_shipment():
    if not session.get("admin_logged_in"):
        return redirect(url_for("login_page"))

    customer = request.form["customer"]
    origin = request.form["origin"]
    destination = request.form["destination"]
    status = request.form["status"].title()

    tracking_number = generate_tracking_number()

    conn = get_db_connection()

    conn.execute(
        "INSERT INTO packages (tracking_number, customer, origin, destination, status) VALUES (?, ?, ?, ?,?)",
        (tracking_number, customer, origin, destination, status)
        )
    
    conn.execute(
    "INSERT INTO tracking_history (tracking_number, update_message, update_time) VALUES (?, ?, datetime('now'))",
    (tracking_number, "Shipment Created")
)

    conn.commit()
    conn.close()

    return render_template(
    "shipment_success.html",
    tracking_number=tracking_number,
    customer=customer,
    origin=origin,
    destination=destination,
    status=status
)
@app.route("/novatrack-update")
def update_page():
     if not session.get("admin_logged_in"):
        return redirect(url_for("login_page"))
     
     return render_template("update.html")

@app.route("/add-update", methods=["POST"])
def add_update():
    if not session.get("admin_logged_in"):
        return redirect(url_for("login_page"))
    
    tracking_number = request.form["tracking_number"].strip().upper()
    message = request.form["message"].strip()

    conn = get_db_connection()

    package = conn.execute(
        "SELECT * FROM packages WHERE tracking_number = ?",
        (tracking_number,)
    ).fetchone()

    if package:
        conn.execute(
            "INSERT INTO tracking_history (tracking_number, update_message, update_time) VALUES (?, ?, datetime('now'))",
            (tracking_number, message)
        )

        conn.execute(
            "UPDATE packages SET status = ? WHERE tracking_number = ?",
            (message, tracking_number)
        )

        conn.commit()
        conn.close()

        return f"""
        <h2>Update Added Successfully</h2>
        <p><strong>Tracking Number:</strong> {tracking_number}</p>
        <p><strong>New Update:</strong> {message}</p>
        <br>
        <a href="/novatrack-update">Add Another Update</a>
        """

    else:
        conn.close()
        return f"""
        <h2>Package Not Found</h2>
        <p>No package was found with tracking number <strong>{tracking_number}</strong>.</p>
        <br>
        <a href="/novatrack-update">Go Back</a>
        """
    
@app.route("/login")
def login_page():
        return render_template("login.html")
    
@app.route("/login", methods=["POST"])
def login():
    username = request.form["username"]
    password = request.form["password"]

    admin_username = "admin"
    admin_password = "12345"

    if username == admin_username and password == admin_password:
        session["admin_logged_in"] = True
        return redirect(url_for("dashboard"))
    else:
        return render_template("login.html", error="Invalid username or password")
    
@app.route("/logout")
def logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("login_page"))

@app.route("/dashboard")
def dashboard():
    if not session.get("admin_logged_in"):
        return redirect(url_for("login_page"))

    search_query = request.args.get("search", "").strip()

    conn = get_db_connection()

    total_shipments = conn.execute(
        "SELECT COUNT(*) FROM packages"
    ).fetchone()[0]

    delivered = conn.execute(
        "SELECT COUNT(*) FROM packages WHERE status = ?",
        ("Delivered",)
    ).fetchone()[0]

    in_transit = conn.execute(
        "SELECT COUNT(*) FROM packages WHERE status = ?",
        ("In Transit",)
    ).fetchone()[0]

    out_for_delivery = conn.execute(
        "SELECT COUNT(*) FROM packages WHERE status = ?",
        ("Out for Delivery",)
    ).fetchone()[0]

    if search_query:
        shipments = conn.execute(
            "SELECT * FROM packages WHERE tracking_number LIKE ? ORDER BY rowid DESC",
            (f"%{search_query}%",)
        ).fetchall()
    else:
        shipments = conn.execute(
            "SELECT * FROM packages ORDER BY rowid DESC LIMIT 10"
        ).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        total_shipments=total_shipments,
        delivered=delivered,
        in_transit=in_transit,
        out_for_delivery=out_for_delivery,
        shipments=shipments,
        search_query=search_query
    )

@app.route("/view-shipment/<tracking_number>")
def view_shipment(tracking_number):
    if not session.get("admin_logged_in"):
        return redirect(url_for("login_page"))

    conn = get_db_connection()

    package = conn.execute(
        "SELECT * FROM packages WHERE tracking_number = ?",
        (tracking_number,)
    ).fetchone()

    history = conn.execute(
        "SELECT * FROM tracking_history WHERE tracking_number = ? ORDER BY id ASC",
        (tracking_number,)
    ).fetchall()

    conn.close()

    return render_template(
        "result.html",
        tracking_number=tracking_number,
        package=package,
        history=history
    )

create_tables()

if __name__ == "__main__":
    app.run(debug=True)