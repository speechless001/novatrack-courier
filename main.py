from flask import Flask, render_template, request, redirect, url_for, session
import os
import random
import string
from datetime import datetime
import pytz
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = True


def get_db_connection():
    return psycopg.connect(
        os.environ["DATABASE_URL"],
        row_factory=dict_row
    )


def create_tables():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS packages (
        tracking_number TEXT PRIMARY KEY,
        customer TEXT,
        origin TEXT,
        destination TEXT,
        status TEXT,
        estimated_delivery TEXT
    
   )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS tracking_history (
        id SERIAL PRIMARY KEY,
        tracking_number TEXT,
        update_message TEXT,
        update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    try:
        cur.execute("ALTER TABLE packages ADD COLUMN estimated_delivery TEXT")
    except Exception:
        conn.rollback()

    conn.commit()
    cur.close()
    conn.close()


def generate_tracking_number():
    conn = get_db_connection()
    cur = conn.cursor()

    while True:
        part1 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        part2 = random.randint(1000, 9999)
        part3 = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))

        tracking_number = f"NVT-US-{part1}-{part2}-{part3}"

        cur.execute(
            "SELECT * FROM packages WHERE tracking_number = %s",
            (tracking_number,)
        )
        existing = cur.fetchone()

        if not existing:
            cur.close()
            conn.close()
            return tracking_number


def format_history_timestamps(history):
    for item in history:
        raw_time = item["update_time"]

        if isinstance(raw_time, str):
            raw_time = datetime.fromisoformat(raw_time)

        item["formatted_time"] = raw_time.strftime("%b %d, %Y • %I:%M %p")

    return history


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/track", methods=["POST"])
def track_package():
    tracking_number = request.form["tracking_number"].strip()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM packages WHERE tracking_number = %s",
        (tracking_number,)
    )
    package = cur.fetchone()

    cur.execute(
        "SELECT * FROM tracking_history WHERE tracking_number = %s ORDER BY id DESC",
        (tracking_number,)
    )
    history = cur.fetchall()

    usa_tz = pytz.timezone("America/New_York")

    if not history:
      history = []
    for item in history:
        raw_time = item["update_time"]

        if isinstance(raw_time, str):
            raw_time = datetime.fromisoformat(raw_time)

        raw_time = raw_time.astimezone(usa_tz)
        item["formatted_time"] = raw_time.strftime("%b %d, %Y • %I:%M %p")
    if "update message" not in item or not item ["update message"]:
     item["update message"] = "shipment update"

     cur.close()
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
    estimated_deivery = request.form["estimated_delivery"].strip()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "INSERT INTO packages (tracking_number, customer, origin, destination, status, estimated_delivery) VALUES (%s, %s, %s, %s, %s)",
        (tracking_number, customer, origin, destination, status)
    )

    cur.execute(
        "INSERT INTO tracking_history (tracking_number, update_message) VALUES (%s, %s)",
        (tracking_number, "Shipment information recieved. Package is awaiting pickup")
    )

    conn.commit()
    cur.close()
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

    tracking_number = request.form["tracking_number"].strip()
    message = request.form["message"].strip()
    status_messages = {
        "Shipment Created": "Shipment information recieved. Package is awaiting pickup.",
        "Arrived at Facility": "package has arrived at a NovaTrack sorting facility.",
        "In Transit": "Package is moving through the NovaTrack delivery network.",
        "Out For Delivery": "Package is out for delivery and is expected to arrive today.",
        "Delayed": "Delivery has been delayed due to operational or route conditions.",
        "Delivered": "Package has been delivered successfully.",
    }
    messages = status_messages.get(message, message)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM packages WHERE tracking_number = %s",
        (tracking_number,)
    )
    package = cur.fetchone()

    if package:
        cur.execute(
            "INSERT INTO tracking_history (tracking_number, update_message) VALUES (%s, %s)",
            (tracking_number, message)
        )

        cur.execute(
            "UPDATE packages SET status = %s WHERE tracking_number = %s",
            (message, tracking_number)
        )

        conn.commit()
        cur.close()
        conn.close()

        return f"""
        <h2>Update Added Successfully</h2>
        <p><strong>Tracking Number:</strong> {tracking_number}</p>
        <p><strong>New Update:</strong> {message}</p>
        <br>
        <a href="/novatrack-update">Add Another Update</a>
        """
    else:
        cur.close()
        conn.close()

        return f"""
        <h2>Package Not Found</h2>
        <p>No package was found with tracking number <strong>{tracking_number}</strong></p>
        <br>
        <a href="/novatrack-update">Go Back</a>
        """


@app.route("/login")
def login_page():
    if session.get("admin_logged_in"):
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/login", methods=["POST"])
def login():
    username = request.form["username"]
    password = request.form["password"]

    admin_username = os.environ.get("ADMIN_USERNAME","admin")

    admin_password = os.environ.get("ADMIN_PASSWORD", "12345")

    if username == admin_username and check_password_hash(admin_password,password):
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
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS count FROM packages")
    total_shipments = cur.fetchone()["count"]

    cur.execute(
        "SELECT COUNT(*) AS count FROM packages WHERE status = %s",
        ("Delivered",)
    )
    delivered = cur.fetchone()["count"]

    cur.execute(
        "SELECT COUNT(*) AS count FROM packages WHERE status = %s",
        ("In Transit",)
    )
    in_transit = cur.fetchone()["count"]

    cur.execute(
        "SELECT COUNT(*) AS count FROM packages WHERE status = %s",
        ("Out for Delivery",)
    )
    out_for_delivery = cur.fetchone()["count"]

    if search_query:
        cur.execute(
            """
            SELECT * FROM packages
            WHERE tracking_number ILIKE %s
            OR customer ILIKE %s
            ORDER BY tracking_number DESC
            """,
            (f"%{search_query}%", f"%{search_query}%")
        )
        shipments = cur.fetchall()
    else:
        cur.execute(
            "SELECT * FROM packages ORDER BY tracking_number DESC"
        )
        shipments = cur.fetchall()

    cur.close()
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
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM packages WHERE tracking_number = %s",
        (tracking_number,)
    )
    package = cur.fetchone()

    cur.execute(
        "SELECT * FROM tracking_history WHERE tracking_number = %s ORDER BY id ASC",
        (tracking_number,)
    )
    history = cur.fetchall()

    cur.close()
    conn.close()

    history = format_history_timestamps(history)

    return render_template(
        "result.html",
        tracking_number=tracking_number,
        package=package,
        history=history
    )
@app.route("/edit-shipment/<tracking_number>")
def edit_shipment_page(tracking_number):
    if not session.get("admin_logged_in"):
        return redirect(url_for("login_page"))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM packages WHERE tracking_number = %s",
        (tracking_number,)
    )
    package = cur.fetchone()

    cur.close()
    conn.close()

    if not package:
        return "Shipment not found", 404

    return render_template("edit_shipment.html", package=package)


@app.route("/edit-shipment/<tracking_number>", methods=["POST"])
def edit_shipment(tracking_number):
    if not session.get("admin_logged_in"):
        return redirect(url_for("login_page"))

    customer = request.form["customer"].strip()
    origin = request.form["origin"].strip()
    destination = request.form["destination"].strip()
    status = request.form["status"].strip()

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE packages
        SET customer = %s, origin = %s, destination = %s, status = %s
        WHERE tracking_number = %s
        """,
        (customer, origin, destination, status, tracking_number)
    )

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("dashboard"))

@app.route("/delete-shipment/<tracking_number>", methods=["POST"])
def delete_shipment(tracking_number):
    if not session.get("admin_logged_in"):
        return redirect(url_for("login_page"))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        "DELETE FROM tracking_history WHERE tracking_number = %s",
        (tracking_number,)
    )

    cur.execute(
        "DELETE FROM packages WHERE tracking_number = %s",
        (tracking_number,)
    )

    conn.commit()
    cur.close()
    conn.close()

    return redirect(url_for("dashboard"))


create_tables()

if __name__ == "__main__":
    app.run(debug=True)